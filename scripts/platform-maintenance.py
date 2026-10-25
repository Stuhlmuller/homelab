#!/usr/bin/env python3
"""Guard the reviewed Talos and Kubernetes maintenance ladder."""

import argparse
import base64
import hashlib
import http.client
import ipaddress
import json
import os
import re
import select
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIN_SHA256 = "e296e99fb36c7b6e3d6e798a93d13afd5a93641efdd409d91fd73772377c840b"
NODES = ("zimaboard-0", "zimaboard-1", "zimaboard-2", "acer")
ADDRESSES = ("10.1.0.200", "10.1.0.201", "10.1.0.202", "10.1.0.199")
RECEIPTS = ("placement", "direct-recovery", "off-node-etcd-backup", "artifact-publication")
SHA = re.compile(r"[0-9a-f]{40}\Z")
RECEIPT_PREFIX = "openclaw-enterprise/platform/upgrade"
PREREQUISITE_PREFIX = "openclaw-enterprise/platform/receipts"
MAX_RECOVERY_AGE_SECONDS = 6 * 60 * 60
PROBE_NAMESPACE = "monitoring"
PROBE_NAME = "platform-maintenance-probe"
PROBE_NODE = "zimaboard-1"
PROBE_IMAGE = ("harbor.stinkyboi.com/mirror/cgr.dev/chainguard/python:"
               "1c4deeea85db49ab5f6bcd9e7fc0bf3fd8439e99f7bde45330f40400685eb394"
               "@sha256:1c4deeea85db49ab5f6bcd9e7fc0bf3fd8439e99f7bde45330f40400685eb394")
PROBE_SCRIPT = ROOT / "scripts/ci/platform-maintenance-pod-probe.py"


def receipt_target():
    result = subprocess.run(
        ["terragrunt", "render", "--config", str(ROOT / "IaC/application-backup-storage.hcl"),
         "--json", "--write=false", "--log-disable"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout)["inputs"]


class DurableReceipts:
    """Write-once, versioned S3 markers for irreversible platform actions."""

    def __init__(self, target):
        if (target.get("account_id") != "716182248480" or
                target.get("region") != "us-east-1" or
                target.get("bucket") != "homelab-application-backups-716182248480-us-east-1"):
            raise ValueError("unreviewed platform receipt destination")
        self.target = target

    def call(self, service, operation, arguments=()):
        region = self.target["region"]
        endpoint = f"https://{'s3' if service == 's3api' else 'sts'}.{region}.amazonaws.com"
        command = ["aws", "--region", region, "--endpoint-url", endpoint,
                   "--output", "json", "--no-cli-pager", "--no-cli-auto-prompt",
                   "--cli-connect-timeout", "15", "--cli-read-timeout", "120",
                   service, operation]
        if service == "s3api":
            command += ["--bucket", self.target["bucket"],
                        "--expected-bucket-owner", self.target["account_id"]]
        result = subprocess.run(command + list(arguments), capture_output=True,
                                text=True, timeout=180, check=False)
        if result.returncode:
            raise ValueError(f"durable platform receipt {operation} failed")
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError("invalid platform receipt metadata")
        return value

    def check(self):
        if self.call("sts", "get-caller-identity").get("Account") != self.target["account_id"]:
            raise ValueError("platform receipt account differs from reviewed owner")
        if self.call("s3api", "get-bucket-versioning").get("Status") != "Enabled":
            raise ValueError("platform receipt bucket is not versioned")
        rules = self.call("s3api", "get-bucket-encryption").get(
            "ServerSideEncryptionConfiguration", {}).get("Rules", [])
        if not rules or rules[0].get("ApplyServerSideEncryptionByDefault", {}).get(
                "SSEAlgorithm") != "aws:kms":
            raise ValueError("platform receipt bucket is not KMS encrypted")

    @staticmethod
    def key(stage, node, status):
        if not re.fullmatch(r"(?:talos|kubernetes)-\d+\.\d+\.\d+", stage):
            raise ValueError("unreviewed durable receipt stage")
        if node is not None and node not in NODES:
            raise ValueError("unreviewed durable receipt node")
        if status not in ("started", "verified"):
            raise ValueError("unreviewed durable receipt status")
        name = f"nodes/{node}" if node else "stage"
        return f"{RECEIPT_PREFIX}/{stage}/{name}/{status}.json"

    def versions(self, stage):
        prefix = f"{RECEIPT_PREFIX}/{stage}/"
        result = self.call("s3api", "list-object-versions", ["--prefix", prefix])
        if result.get("IsTruncated") is True or result.get("DeleteMarkers"):
            raise ValueError("platform receipt history is incomplete or deleted")
        expected = {self.key(stage, node, status)
                    for node in (None, *NODES) for status in ("started", "verified")}
        versions = {}
        for item in result.get("Versions", []):
            key, version = item.get("Key"), item.get("VersionId")
            if (key not in expected or key in versions or not isinstance(version, str) or
                    not version or version == "null" or item.get("IsLatest") is not True):
                raise ValueError("ambiguous durable platform receipt history")
            versions[key] = version
        return versions

    def download(self, key, version, directory):
        fd, name = tempfile.mkstemp(prefix=".platform-receipt-", dir=directory)
        os.close(fd)
        path = Path(name)
        try:
            metadata = self.call("s3api", "get-object", [
                "--key", key, "--version-id", version, "--checksum-mode", "ENABLED",
                str(path)])
            content = path.read_bytes()
            checksum = base64.b64encode(hashlib.sha256(content).digest()).decode()
            if (not content or len(content) > 1048576 or
                    metadata.get("VersionId") != version or
                    metadata.get("ContentLength") != len(content) or
                    metadata.get("ChecksumSHA256") != checksum or
                    metadata.get("ServerSideEncryption") != "aws:kms"):
                raise ValueError("durable platform receipt readback differs")
            json.loads(content)
            return content
        finally:
            path.unlink(missing_ok=True)

    def write(self, stage, node, status, path):
        path = private_output(path)
        read_private_json(path)
        key = self.key(stage, node, status)
        if key in self.versions(stage):
            raise ValueError("durable platform receipt already exists")
        content = path.read_bytes()
        checksum = base64.b64encode(hashlib.sha256(content).digest()).decode()
        response = self.call("s3api", "put-object", [
            "--key", key, "--body", str(path), "--if-none-match", "*",
            "--checksum-algorithm", "SHA256", "--checksum-sha256", checksum,
            "--server-side-encryption", "aws:kms", "--ssekms-key-id",
            f"arn:aws:kms:{self.target['region']}:{self.target['account_id']}:alias/aws/s3",
            "--bucket-key-enabled"])
        version = response.get("VersionId")
        if (not isinstance(version, str) or not version or version == "null" or
                response.get("ChecksumSHA256") != checksum or
                self.versions(stage).get(key) != version or
                self.download(key, version, path.parent) != content):
            raise ValueError("durable platform receipt write was not verified")

    def restore(self, stage, directory):
        directory = private_directory(directory)
        versions = self.versions(stage)
        records = {}
        for node in (None, *NODES):
            for status in ("started", "verified"):
                key = self.key(stage, node, status)
                if key in versions:
                    records[(node, status)] = self.download(key, versions[key], directory)
            started = records.get((node, "started"))
            verified = records.get((node, "verified"))
            if node is None and stage.startswith("kubernetes-") and verified and not started:
                raise ValueError("verified Kubernetes stage has no durable start marker")
            if node is not None and verified is not None:
                if started is None:
                    raise ValueError("verified node has no durable start marker")
                before, after = json.loads(started), json.loads(verified)
                if (not isinstance(before, dict) or not isinstance(after, dict) or
                        before.get("format") != 1 or before.get("stage") != stage or
                        before.get("node") != node or
                        before.get("pinSha256") != PIN_SHA256 or
                        not isinstance(before.get("sourceSha"), str) or
                        not SHA.fullmatch(before["sourceSha"]) or
                        not isinstance(before.get("from"), str) or
                        not isinstance(before.get("to"), str) or
                        before["from"] == before["to"] or
                        before.get("status") != "started" or before.get("verified") is not False or
                        after.get("status") != "verified" or after.get("verified") is not True or
                        not isinstance(after.get("evidence"), dict) or
                        after["evidence"].get("observedVersion") != before.get("to") or
                        after["evidence"].get("ready") is not True or
                        after["evidence"].get("clusterHealth") is not True or
                        not after["evidence"].get("bootID") or
                        {k: after.get(k) for k in before} != {**before, "status": "verified", "verified": True}):
                    raise ValueError("durable node completion differs from its start")
            if node is None and started is not None and verified is None:
                pending = json.loads(started)
                if (not isinstance(pending, dict) or
                        pending.get("stage") != stage or pending.get("status") != "started" or
                        pending.get("verified") is not False):
                    raise ValueError("durable Kubernetes start marker is invalid")
            selected = verified or started
            path = (directory / f"{stage}--{node}.json" if node is not None
                    else directory / f"{stage}.json")
            if selected is None:
                if path.exists() or path.is_symlink():
                    raise ValueError("runner-local platform receipt has no durable copy")
                continue
            if path.exists() or path.is_symlink():
                if read_private_json(path) != json.loads(selected) or path.read_bytes() != selected:
                    raise ValueError("runner-local platform receipt differs from durable copy")
                continue
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(selected)
                output.flush()
                os.fsync(output.fileno())

    def load_one(self, key, path):
        result = self.call("s3api", "list-object-versions", ["--prefix", key])
        versions = result.get("Versions", [])
        if (result.get("IsTruncated") is True or result.get("DeleteMarkers") or
                not isinstance(versions, list) or len(versions) != 1 or
                versions[0].get("Key") != key or
                versions[0].get("IsLatest") is not True or
                not isinstance(versions[0].get("VersionId"), str) or
                versions[0]["VersionId"] in ("", "null")):
            raise ValueError("private prerequisite is missing or has ambiguous history")
        content = self.download(key, versions[0]["VersionId"], path.parent)
        if path.exists() or path.is_symlink():
            if read_private_json(path) != json.loads(content) or path.read_bytes() != content:
                raise ValueError("runner-local prerequisite differs from durable copy")
            return
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())

    def load_prerequisites(self, source_sha, directory):
        """Restore one immutable, checksummed version of each current-SHA gate."""
        if not isinstance(source_sha, str) or not SHA.fullmatch(source_sha):
            raise ValueError("invalid prerequisite source revision")
        directory = private_directory(directory)
        for name in RECEIPTS:
            key = f"{PREREQUISITE_PREFIX}/{source_sha}/{name}.json"
            self.load_one(key, directory / f"{name}.json")

    def load_istio_completions(self, config, directory):
        directory = private_directory(directory)
        for item in config["istioStages"]:
            stage = f"istio-{item['to']}"
            key = f"openclaw-enterprise/platform/stages/{stage}/verified.json"
            self.load_one(key, directory / f"{stage}.json")


def validate_config(config):
    if not isinstance(config, dict) or config.get("schemaVersion") != 1:
        raise ValueError("unsupported maintenance input")
    if config.get("protectedTalosEndpoint") != "talos-api.homelab.local.stinkyboi.com:15000":
        raise ValueError("unreviewed authenticated Talos transport")
    pins = {name: config.get(name) for name in ("talosStages", "istioStages", "kubernetesStage")}
    digest = hashlib.sha256(json.dumps(pins, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != PIN_SHA256:
        raise ValueError("unreviewed platform version or artifact")
    start = config.get("expectedStart")
    if not isinstance(start, dict) or not isinstance(start.get("nodes"), dict):
        raise ValueError("starting node inventory is missing")
    if (start.get("talos"), start.get("kubernetes"), start.get("istio")) != (
            "1.11.3", "1.34.11", "1.27.3"):
        raise ValueError("unexpected starting platform versions")
    if (start.get("controlPlane") != "acer" or
            tuple(start.get("workers", ())) != NODES[:-1] or
            tuple(config.get("nodeOrder", ())) != NODES or
            set(start["nodes"]) != set(NODES) or
            any(not isinstance(start["nodes"][node], dict) or
                start["nodes"][node].get("role") != ("control-plane" if node == "acer" else "worker") or
                start["nodes"][node].get("address") != address
                for node, address in zip(NODES, ADDRESSES))):
        raise ValueError("unreviewed node order or role")
    canary = config.get("canary", {})
    if (canary.get("node") is not None and canary.get("node") not in NODES[:-1]) or (
            canary.get("requiresDedicatedTaint") is not True or
            canary.get("requiresMeasuredPlacement") is not True or
            canary.get("label") != "homelab.stinkyboi.com/network-policy-canary" or
            canary.get("taint") != "homelab.stinkyboi.com/network-policy-canary=true:NoSchedule"):
        raise ValueError("unreviewed canary admission")
    if (tuple(config.get("requiredPrivateReceipts", ())) != RECEIPTS or
            config.get("sourceRevisionPolicy") != "exact-current-main-sha-from-protected-workflow" or
            type(config.get("activationEnabled")) is not bool or
            any(type(value) is not int or value <= 0
                for value in config.get("readinessDeadlineSeconds", {}).values()) or
            set(config.get("readinessDeadlineSeconds", {})) != {"node", "api", "storage", "mesh"}):
        raise ValueError("unreviewed maintenance execution contract")
    return config


def fresh_recovery_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise ValueError("private recovery timestamp is invalid")
    captured = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - captured).total_seconds()
    if not 0 <= age <= MAX_RECOVERY_AGE_SECONDS:
        raise ValueError("private recovery evidence is stale or in the future")


def verify_prerequisites(config, source_sha, receipts):
    if (not isinstance(receipts, dict) or
            any(not isinstance(receipts.get(name), dict) or
                receipts[name].get("sourceSha") != source_sha or
                receipts[name].get("verified") is not True for name in RECEIPTS)):
        raise ValueError("private recovery evidence is missing or stale")
    placement = receipts["placement"]
    if (placement.get("canaryNode") != config["canary"]["node"] or
            placement.get("measured") is not True or
            placement.get("isolatedTaint") != config["canary"]["taint"]):
        raise ValueError("measured isolated canary placement is missing")
    recovery = receipts["direct-recovery"]
    fresh_recovery_time(recovery.get("capturedAt"))
    if (recovery.get("transport") != "direct-lan-authenticated-talos" or
            recovery.get("endpoint") != "10.1.0.199:50000" or
            recovery.get("nodes") != list(NODES) or
            recovery.get("talosMtls") is not True):
        raise ValueError("direct-LAN Talos recovery was not proved")
    backup = receipts["off-node-etcd-backup"]
    fresh_recovery_time(backup.get("capturedAt"))
    if (backup.get("offNode") is not True or
            backup.get("offlineRestoreVerified") is not True or
            not isinstance(backup.get("snapshotSha256"), str) or
            not re.fullmatch(r"[0-9a-f]{64}", backup["snapshotSha256"]) or
            not isinstance(backup.get("objectVersionId"), str) or
            backup["objectVersionId"] in ("", "null")):
        raise ValueError("fresh off-node etcd recovery proof is incomplete")


def authorize_stage(config, stage, expected_sha, current_sha, receipts):
    validate_config(config)
    stages = [f"talos-{item['to']}" for item in config["talosStages"]]
    stages += [f"istio-{item['to']}" for item in config["istioStages"]]
    stages.append(f"kubernetes-{config['kubernetesStage']['to']}")
    if (not config["activationEnabled"] or config["canary"]["node"] is None or
            not isinstance(expected_sha, str) or not SHA.fullmatch(expected_sha) or
            expected_sha != current_sha or stage not in stages):
        raise ValueError("maintenance stage is not authorized on current main")
    if not isinstance(receipts, dict):
        raise ValueError("private recovery evidence is missing")
    for name in RECEIPTS:
        receipt = receipts.get(name)
        if (not isinstance(receipt, dict) or receipt.get("sourceSha") != expected_sha or
                receipt.get("verified") is not True):
            raise ValueError("private recovery evidence is missing or stale")
    verify_prerequisites(config, expected_sha, receipts)
    for prior in stages[:stages.index(stage)]:
        receipt = receipts.get(prior)
        if (not isinstance(receipt, dict) or not isinstance(receipt.get("sourceSha"), str) or
                not SHA.fullmatch(receipt["sourceSha"]) or receipt.get("verified") is not True):
            raise ValueError("preceding maintenance stage is unverified")
        if prior.startswith("istio-") and (
                receipt.get("stage") != prior or receipt.get("pinSha256") != PIN_SHA256 or
                receipt.get("observedVersion") != prior.removeprefix("istio-")):
            raise ValueError("preceding Istio stage is not bound to the reviewed ladder")
    return stage


def node_action(node, source_version, target_version, observed_version, observed_boot_id,
                receipt, source_sha, stage):
    if (node not in NODES or source_version == target_version or
            not isinstance(source_sha, str) or not SHA.fullmatch(source_sha) or
            not isinstance(observed_boot_id, str) or not observed_boot_id):
        raise ValueError("unreviewed node or version transition")
    if receipt is None and observed_version == source_version:
        return "upgrade"
    evidence = receipt.get("evidence") if isinstance(receipt, dict) else None
    if (isinstance(receipt, dict) and receipt.get("format") == 1 and
            receipt.get("node") == node and receipt.get("from") == source_version and
            receipt.get("to") == target_version and receipt.get("verified") is True and
            receipt.get("status") == "verified" and
            receipt.get("pinSha256") == PIN_SHA256 and
            isinstance(receipt.get("sourceSha"), str) and SHA.fullmatch(receipt["sourceSha"]) and
            receipt.get("stage") == stage and observed_version == target_version and
            isinstance(evidence, dict) and evidence.get("bootID") == observed_boot_id and
            evidence.get("observedVersion") == target_version and
            evidence.get("ready") is True and evidence.get("clusterHealth") is True):
        verify_path_probe(evidence.get("pathProbe"), stage, node, receipt["sourceSha"])
        return "skip"
    raise ValueError("interrupted or unknown node state requires recovery review")


def private_directory(path):
    if path is None or not path.is_absolute():
        raise ValueError("private evidence needs an absolute directory")
    path = path.resolve(strict=True)
    info = path.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
            stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError("private evidence directory must be owned and mode 0700")
    if any((directory / ".git").exists() for directory in (path, *path.parents)):
        raise ValueError("private evidence must be outside Git checkouts")
    return path


def private_output(path):
    if path is None:
        raise ValueError("private output path is missing")
    return private_directory(path.parent) / path.name


def read_receipts(path):
    directory = private_directory(path)
    receipts = {}
    for entry in directory.iterdir():
        if entry.suffix != ".json":
            continue
        name = entry.stem
        if re.fullmatch(r"(?:talos|kubernetes)-\d+\.\d+\.\d+--(?:zimaboard-[0-2]|acer)", name):
            continue
        if name not in RECEIPTS and not re.fullmatch(r"(?:talos|istio|kubernetes)-\d+\.\d+\.\d+", name):
            raise ValueError("unreviewed private maintenance receipt")
        receipts[name] = read_private_json(entry)
    return receipts


def read_private_json(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
            stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 1048576):
        raise ValueError("private maintenance receipt is unsafe")
    return json.loads(path.read_text())


def node_receipt_path(directory, stage, node):
    directory = private_directory(directory)
    if node not in NODES or not re.fullmatch(r"(?:talos|kubernetes)-\d+\.\d+\.\d+", stage):
        raise ValueError("unreviewed per-node receipt identity")
    return directory / f"{stage}--{node}.json"


def read_node_receipt(directory, stage, node):
    path = node_receipt_path(directory, stage, node)
    return read_private_json(path) if path.exists() or path.is_symlink() else None


def start_node_receipt(directory, stage, node, source, target, source_sha, store=None):
    path = node_receipt_path(directory, stage, node)
    save_inspection(path, {"format": 1, "stage": stage, "node": node,
                           "from": source, "to": target, "sourceSha": source_sha,
                           "pinSha256": PIN_SHA256,
                           "verified": False, "status": "started"})
    if store is not None:
        store.write(stage, node, "started", path)
    return path


def complete_node_receipt(directory, stage, node, source_sha, evidence, store=None):
    path = node_receipt_path(directory, stage, node)
    pending = read_private_json(path)
    if (pending.get("stage") != stage or pending.get("node") != node or
            pending.get("sourceSha") != source_sha or pending.get("status") != "started" or
            pending.get("pinSha256") != PIN_SHA256 or
            pending.get("verified") is not False or not isinstance(evidence, dict) or
            evidence.get("observedVersion") != pending.get("to") or
            evidence.get("ready") is not True or evidence.get("clusterHealth") is not True or
            not isinstance(evidence.get("bootID"), str) or not evidence["bootID"]):
        raise ValueError("pending node receipt does not match execution")
    verify_path_probe(evidence.get("pathProbe"), stage, node, source_sha)
    record = {**pending, "status": "verified", "verified": True, "evidence": evidence}
    temporary = path.with_name(f".{path.name}.complete")
    save_inspection(temporary, record)
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    if store is not None:
        store.write(stage, node, "verified", path)
    return record


def current_main_sha():
    result = subprocess.run(
        ["gh", "api", "repos/Stuhlmuller/homelab/branches/main", "--jq", ".commit.sha"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    value = result.stdout.strip()
    if not SHA.fullmatch(value):
        raise ValueError("current main SHA is unavailable")
    return value


def talos_upgrade_command(config, stage, node, talosconfig):
    if node not in NODES:
        raise ValueError("unreviewed Talos node")
    target = next((item for item in config["talosStages"]
                   if stage == f"talos-{item['to']}"), None)
    if target is None:
        raise ValueError("unreviewed Talos upgrade stage")
    address = config["expectedStart"]["nodes"][node]["address"]
    return ["talosctl", "--talosconfig", str(talosconfig), "--endpoints",
            config["protectedTalosEndpoint"],
            "--nodes", address, "upgrade", "--image", target["installerImage"],
            "--wait", "--timeout", f"{config['readinessDeadlineSeconds']['node']}s"]


def kubernetes_upgrade_command(config, talosconfig, catalog):
    """Talos appends the target tag, so bind each base to a published digest first."""
    target = config["kubernetesStage"]
    version = target["to"]
    sources = {entry["source"] for entry in catalog.get("images", [])}
    flags = (("kube-apiserver", "--apiserver-image"),
             ("kube-controller-manager", "--controller-manager-image"),
             ("kube-scheduler", "--scheduler-image"),
             ("kube-proxy", "--proxy-image"),
             ("kubelet", "--kubelet-image"))
    control = config["expectedStart"]["nodes"]["acer"]["address"]
    command = ["talosctl", "--talosconfig", str(talosconfig), "--endpoints",
               config["protectedTalosEndpoint"],
               "--nodes", control, "upgrade-k8s", "--from", target["from"],
               "--to", version, "--endpoint", f"https://{control}:6443"]
    for component, flag in flags:
        source = target["images"][component]
        suffix = f":v{version}@sha256:"
        if source not in sources or source.count(suffix) != 1:
            raise ValueError("Kubernetes target image is not bound to the reviewed catalog")
        base, digest = source.split(suffix)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Kubernetes target image digest is invalid")
        command.extend((flag, base))
    return command


def active_machine_state(config, talosconfig, node):
    """Read the active and persistent Talos config without exposing its secrets."""
    address = config["expectedStart"]["nodes"][node]["address"]
    result = subprocess.run(
        ["talosctl", "--talosconfig", str(talosconfig), "--endpoints",
         config["protectedTalosEndpoint"], "--nodes", address,
         "get", "machineconfig", "-o", "json"],
        capture_output=True, text=True, timeout=60, check=True)
    decoder = json.JSONDecoder()
    stream = result.stdout.strip()
    resources = {}
    while stream:
        resource, consumed = decoder.raw_decode(stream)
        metadata = resource.get("metadata", {})
        identity = metadata.get("id")
        if (identity not in ("v1alpha1", "persistent") or identity in resources or
                metadata.get("namespace") != "config" or
                metadata.get("type") != "MachineConfigs.config.talos.dev" or
                metadata.get("phase") != "running" or
                not isinstance(resource.get("spec"), str)):
            raise ValueError("Talos machine config state is ambiguous")
        resources[identity] = resource
        stream = stream[consumed:].strip()
    if "v1alpha1" not in resources:
        raise ValueError("active Talos machine config is missing")
    if ("persistent" not in resources and
            resources["v1alpha1"]["metadata"].get("version") != 1):
        raise ValueError("active Talos machine config has no persistent counterpart")

    def decode_machine(source):
        rendered = subprocess.run(
            ["yq", "ea", "-o=json", "-I=0",
             ". as $item ireduce ([]; . + [$item])", "-"], input=source,
            capture_output=True, text=True, timeout=30, check=True)
        documents = json.loads(rendered.stdout)
        configs = [item for item in documents if isinstance(item, dict) and
                   item.get("version") == "v1alpha1"]
        if len(configs) != 1 or not isinstance(configs[0].get("machine"), dict):
            raise ValueError("Talos machine config has no unique machine document")
        return documents, configs[0]["machine"]

    active_docs, machine = decode_machine(resources["v1alpha1"]["spec"])
    if ("persistent" in resources and
            decode_machine(resources["persistent"]["spec"])[0] != active_docs):
        raise ValueError("active and persistent Talos machine configs differ")
    role = "controlplane" if node == "acer" else "worker"
    install = machine.get("install", {})
    disk = install.get("disk") if isinstance(install, dict) else None
    if (machine.get("type") != role or not isinstance(disk, str) or
            not disk.startswith("/dev/") or disk == "/dev/"):
        raise ValueError("Talos role or install disk differs from reviewed node")
    registries = machine.get("registries", {})
    if not isinstance(registries, dict) or not isinstance(registries.get("mirrors", {}), dict):
        raise ValueError("Talos registry mirror config is malformed")
    return {"role": role, "disk": disk, "mirrors": registries.get("mirrors", {})}


def verify_kubernetes_mirror_tags(config):
    """Require the five Talos-generated tags to be locked to reviewed digests."""
    version = config["kubernetesStage"]["to"]
    for source in config["kubernetesStage"]["images"].values():
        repository, digest = source.split(f":v{version}@", 1)
        mirror = f"mirror/{repository}"
        encoded = urllib.parse.quote(urllib.parse.quote(repository, safe=""), safe="")
        url = ("https://harbor.stinkyboi.com/api/v2.0/projects/mirror/repositories/"
               f"{encoded}/artifacts/v{version}?with_tag=true&with_immutable_status=true")
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = response.read(1048577)
        if len(payload) > 1048576:
            raise ValueError("Harbor Kubernetes tag response is oversized")
        artifact = json.loads(payload)
        tags = artifact.get("tags") if isinstance(artifact, dict) else None
        if (not isinstance(artifact, dict) or artifact.get("digest") != digest or
                not isinstance(tags, list) or
                len([tag for tag in tags if isinstance(tag, dict) and
                     tag.get("name") == f"v{version}" and tag.get("immutable") is True]) != 1):
            raise ValueError(f"Harbor Kubernetes tag is not locked: {mirror}")


def verify_kubernetes_mirror_routes(config, talosconfig):
    for node in NODES:
        mirrors = active_machine_state(config, talosconfig, node)["mirrors"]
        for registry in ("ghcr.io", "registry.k8s.io"):
            expected = {"endpoints": [f"https://harbor.stinkyboi.com/v2/mirror/{registry}"],
                        "overridePath": True, "skipFallback": True}
            if mirrors.get(registry) != expected:
                raise ValueError("Talos node lacks the reviewed no-fallback Harbor mirror")


def verify_live_istio_target(config):
    """Refuse a Kubernetes hop if the preceding Istio rollout has drifted."""
    target = config["istioStages"][-1]["images"]
    expected = {
        ("Deployment", "istiod"): "pilot",
        ("Deployment", "istio-ingressgateway"): "proxyv2",
        ("Deployment", "octelium-api-ingressgateway"): "proxyv2",
        ("DaemonSet", "istio-cni-node"): "install-cni",
        ("DaemonSet", "ztunnel"): "ztunnel",
    }
    result = subprocess.run(
        ["kubectl", "-n", "istio-system", "get", "deployments,daemonsets", "-o", "json"],
        capture_output=True, text=True, timeout=60, check=True)
    items = json.loads(result.stdout).get("items")
    if not isinstance(items, list):
        raise ValueError("live Istio workload inventory is unavailable")
    found = set()
    gateways = {}
    for item in items:
        identity = (item.get("kind"), item.get("metadata", {}).get("name"))
        if identity not in expected:
            continue
        if identity in found:
            raise ValueError("live Istio workload identity is ambiguous")
        found.add(identity)
        image = target[expected[identity]]
        images = [container.get("image") for container in
                  item.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])]
        if identity[1] in ("istio-ingressgateway", "octelium-api-ingressgateway"):
            if images != ["auto"]:
                raise ValueError("live Istio gateway template is not injected")
        elif images != [image]:
            raise ValueError("live Istio image differs from the reviewed target")
        metadata, spec, status = item["metadata"], item["spec"], item.get("status", {})
        if metadata.get("deletionTimestamp") is not None:
            raise ValueError("live Istio workload is deleting")
        if (not isinstance(metadata.get("generation"), int) or
                status.get("observedGeneration") != metadata["generation"]):
            raise ValueError("live Istio rollout is not observed")
        if identity[0] == "Deployment":
            desired = spec.get("replicas", 1)
            fields = ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas")
        else:
            desired = len(NODES)
            if (status.get("desiredNumberScheduled") != desired or
                    status.get("numberMisscheduled") != 0):
                raise ValueError("live Istio DaemonSet placement is incomplete")
            fields = ("updatedNumberScheduled", "numberReady", "numberAvailable")
        if (not isinstance(desired, int) or desired < 1 or
                any(status.get(field) != desired for field in fields)):
            raise ValueError("live Istio workload is not fully ready")
        if identity[1] in ("istio-ingressgateway", "octelium-api-ingressgateway"):
            selector = spec.get("selector", {}).get("matchLabels")
            if not isinstance(selector, dict) or not selector:
                raise ValueError("live Istio gateway selector is missing")
            gateways[identity[1]] = (selector, desired)
    if found != set(expected):
        raise ValueError("reviewed Istio workload is missing")
    pods = subprocess.run(
        ["kubectl", "-n", "istio-system", "get", "pods", "-o", "json"],
        capture_output=True, text=True, timeout=60, check=True)
    items = json.loads(pods.stdout).get("items")
    if not isinstance(items, list):
        raise ValueError("live Istio gateway Pods are unavailable")
    for gateway, (selector, desired) in gateways.items():
        matching = [pod for pod in items if all(
            pod.get("metadata", {}).get("labels", {}).get(key) == value
            for key, value in selector.items())]
        image = target["proxyv2"]
        if len(matching) < desired or any(
                pod.get("metadata", {}).get("deletionTimestamp") or
                [container.get("image") for container in
                 pod.get("spec", {}).get("containers", [])] != [image] or
                not any(condition.get("type") == "Ready" and condition.get("status") == "True"
                        for condition in pod.get("status", {}).get("conditions", []))
                for pod in matching):
            raise ValueError(f"live Istio gateway Pods are not at the reviewed target: {gateway}")


def verify_installer_mirror_route(machine, image):
    registry = image.split("/", 1)[0]
    if registry not in ("ghcr.io", "factory.talos.dev"):
        raise ValueError("Talos installer registry is not reviewed")
    expected = {"endpoints": [f"https://harbor.stinkyboi.com/v2/mirror/{registry}"],
                "overridePath": True, "skipFallback": True}
    if machine["mirrors"].get(registry) != expected:
        raise ValueError("Talos installer lacks the reviewed no-fallback Harbor mirror")


def verify_stage_receipt(config, stage, summary, receipt_dir):
    target = next((item for item in config["talosStages"]
                   if stage == f"talos-{item['to']}"), None)
    if stage == f"kubernetes-{config['kubernetesStage']['to']}":
        target = config["kubernetesStage"]
    if (target is None or not isinstance(summary, dict) or summary.get("format") != 1 or
            summary.get("stage") != stage or summary.get("verified") is not True or
            not isinstance(summary.get("sourceSha"), str) or
            not SHA.fullmatch(summary["sourceSha"]) or
            not isinstance(summary.get("nodes"), dict) or
            set(summary["nodes"]) != set(NODES)):
        raise ValueError("platform stage receipt is incomplete")
    verify_path_probe(summary.get("pathProbe"), stage, "stage", summary["sourceSha"])
    for node in NODES:
        path = node_receipt_path(receipt_dir, stage, node)
        record = read_private_json(path)
        if (hashlib.sha256(path.read_bytes()).hexdigest() != summary["nodes"][node] or
                not isinstance(record, dict) or
                record.get("format") != 1 or record.get("stage") != stage or
                record.get("node") != node or
                record.get("pinSha256") != PIN_SHA256 or
                not isinstance(record.get("sourceSha"), str) or
                not SHA.fullmatch(record["sourceSha"]) or
                record.get("from") != target["from"] or record.get("to") != target["to"] or
                record.get("verified") is not True or record.get("status") != "verified" or
                not isinstance(record.get("evidence"), dict) or
                record.get("evidence", {}).get("observedVersion") != target["to"] or
                record.get("evidence", {}).get("ready") is not True or
                not record.get("evidence", {}).get("bootID") or
                record.get("evidence", {}).get("clusterHealth") is not True):
            raise ValueError("platform node receipt is incomplete or changed")
        verify_path_probe(record["evidence"].get("pathProbe"), stage, node,
                          record["sourceSha"])
    return summary


def cluster_health(config, talosconfig):
    control = config["expectedStart"]["nodes"]["acer"]["address"]
    workers = ",".join(config["expectedStart"]["nodes"][node]["address"]
                       for node in NODES[:-1])
    subprocess.run(
        ["talosctl", "--talosconfig", str(talosconfig), "--endpoints",
         config["protectedTalosEndpoint"],
         "health", "--control-plane-nodes", control, "--worker-nodes", workers,
         "--wait-timeout", f"{config['readinessDeadlineSeconds']['api']}s"],
        capture_output=True, text=True,
        timeout=config["readinessDeadlineSeconds"]["api"] + 30, check=True,
    )
    api = subprocess.run(["kubectl", "get", "--raw", "/readyz"],
                         capture_output=True, text=True, timeout=30, check=True)
    if api.stdout.strip() != "ok":
        raise ValueError("Kubernetes API readiness failed")


def verify_path_probe(probe, stage, node, source_sha):
    if (not isinstance(probe, dict) or probe.get("format") != 1 or
            probe.get("stage") != stage or probe.get("node") != node or
            probe.get("sourceSha") != source_sha or
            not isinstance(probe.get("capturedAt"), str) or
            not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", probe["capturedAt"])):
        raise ValueError("inter-node path probe identity is incomplete")
    fixture = probe.get("fixture")
    if (not isinstance(fixture, dict) or fixture.get("namespace") != PROBE_NAMESPACE or
            fixture.get("pod") != PROBE_NAME or fixture.get("claim") != PROBE_NAME or
            fixture.get("storageClass") != "nfs-default" or
            fixture.get("node") != PROBE_NODE or
            any(not isinstance(fixture.get(key), str) or not fixture[key]
                for key in ("podUid", "claimUid", "volumeUid"))):
        raise ValueError("inter-node storage fixture proof is incomplete")
    dns = probe.get("dns")
    if (not isinstance(dns, dict) or
            set(dns) != {"kubernetes.default.svc.cluster.local",
                         "grafana.monitoring.svc.cluster.local"}):
        raise ValueError("inter-node DNS proof is incomplete")
    try:
        for address in dns.values():
            ipaddress.IPv4Address(address)
    except (ipaddress.AddressValueError, ValueError, TypeError):
        raise ValueError("inter-node DNS answer is invalid") from None
    storage = probe.get("storage")
    if (not isinstance(storage, dict) or storage.get("bytes") != 4096 or
            storage.get("readBack") is not True or storage.get("deleted") is not True or
            not isinstance(storage.get("sha256"), str) or
            not re.fullmatch(r"[0-9a-f]{64}", storage["sha256"])):
        raise ValueError("inter-node NFS I/O proof is incomplete")
    if (probe.get("access") != {"octeliumKubernetesApi": True, "octeliumTalosMtls": True} or
            probe.get("webhooks") != {"policyBotStatus": 404,
                                      "policyBotRequestId": True,
                                      "n8nStatus": 404, "n8nApplicationBody": True} or
            not isinstance(probe.get("application"), dict) or
            probe["application"].get("grafanaHttpStatus") != 200 or
            probe["application"].get("grafanaDatabase") != "ok" or
            probe["application"].get("service") != "monitoring/grafana" or
            not isinstance(probe["application"].get("serviceUid"), str) or
            not probe["application"]["serviceUid"] or
            not isinstance(probe["application"].get("podUid"), str) or
            not probe["application"]["podUid"] or
            not isinstance(probe["application"].get("pod"), str) or
            not re.fullmatch(r"grafana-[a-z0-9-]+", probe["application"]["pod"])):
        raise ValueError("inter-node access, webhook or application proof is incomplete")
    return probe


def _kubectl_json(*arguments):
    result = subprocess.run(["kubectl", "--request-timeout=15s", *arguments, "-o", "json"],
                            capture_output=True, text=True, timeout=25, check=True)
    return json.loads(result.stdout)


def _webhook_response(host, path, method):
    connection = http.client.HTTPSConnection(host, timeout=10)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        return response.status, response.read(2049), response.getheaders()
    finally:
        connection.close()


def _webhook_path_proof(deadline_seconds):
    """Allow bounded restart recovery; accept only the fixed application responses."""
    deadline = time.monotonic() + deadline_seconds
    while True:
        try:
            policy_status, _, policy_headers = _webhook_response(
                "policy-bot-hook.tail67beb.ts.net", "/api/github/hook", "GET")
            request_ids = [value for key, value in policy_headers
                           if key.lower() == "x-request-id"]
            if policy_status == 404 and (len(request_ids) != 1 or
                                          not re.fullmatch(r"[0-9a-v]{20}", request_ids[0])):
                raise ValueError("Policy Bot webhook application response is invalid")
            if policy_status != 404 and policy_status < 500:
                raise ValueError("Policy Bot webhook path changed")
            if policy_status == 404:
                n8n_status, n8n_body, _ = _webhook_response(
                    "n8n-webhook.tail67beb.ts.net", "/webhook/__octelium_e2e_missing__", "GET")
                if n8n_status == 404 and b"webhook" not in n8n_body.lower():
                    raise ValueError("n8n webhook application response is invalid")
                if n8n_status != 404 and n8n_status < 500:
                    raise ValueError("n8n webhook path changed")
                if n8n_status == 404:
                    return {"policyBotStatus": 404, "policyBotRequestId": True,
                            "n8nStatus": 404, "n8nApplicationBody": True}
        except (OSError, http.client.HTTPException):
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("webhook application paths unavailable after deadline")
        time.sleep(min(5, remaining))


def _grafana_health_via_port_forward(pod_name):
    """Read Grafana's database health over the protected Octelium Kubernetes API."""
    if not re.fullmatch(r"grafana-[a-z0-9-]+", pod_name):
        raise ValueError("unreviewed Grafana Pod identity")
    process = subprocess.Popen(
        ["kubectl", "-n", "monitoring", "port-forward",
         "--address", "127.0.0.1", f"pod/{pod_name}", ":3000"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    try:
        deadline = time.monotonic() + 20
        port = None
        while time.monotonic() < deadline and process.poll() is None:
            readable, _, _ = select.select([process.stdout], [], [],
                                            max(0, min(1, deadline - time.monotonic())))
            if readable:
                line = process.stdout.readline().strip()
                if not line:
                    raise ValueError("Grafana port-forward closed before readiness")
                match = re.fullmatch(r"Forwarding from 127\.0\.0\.1:(\d+) -> 3000", line)
                if match:
                    port = int(match.group(1))
                    break
        if port is None or not 1 <= port <= 65535 or process.poll() is not None:
            raise ValueError("Grafana port-forward did not become ready")
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            try:
                connection.request("GET", "/api/health")
                response = connection.getresponse()
                body = response.read(4097)
            except http.client.HTTPException:
                raise ValueError("Grafana health stream failed") from None
            if (response.status != 200 or len(body) > 4096 or
                    json.loads(body).get("database") != "ok"):
                raise ValueError("Grafana database health path failed")
        finally:
            connection.close()
        if process.poll() is not None:
            raise ValueError("Grafana port-forward ended during health check")
        return {"grafanaHttpStatus": 200, "grafanaDatabase": "ok"}
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()


def inter_node_path_probe(config, talosconfig, stage, node, source_sha):
    """Run fixed functional paths before a node/stage can be marked verified."""
    if (node not in (*NODES, "stage") or
            not re.fullmatch(r"(?:talos|kubernetes)-\d+\.\d+\.\d+", stage) or
            not isinstance(source_sha, str) or not SHA.fullmatch(source_sha)):
        raise ValueError("unreviewed inter-node probe identity")
    wait_seconds = min(config["readinessDeadlineSeconds"]["storage"], 300)
    subprocess.run(
        ["kubectl", "-n", PROBE_NAMESPACE, "wait", "--for=condition=Ready",
         f"pod/{PROBE_NAME}", f"--timeout={wait_seconds}s"],
        capture_output=True, text=True, timeout=wait_seconds + 30, check=True)
    pod = _kubectl_json("-n", PROBE_NAMESPACE, "get", "pod", PROBE_NAME)
    claim = _kubectl_json("-n", PROBE_NAMESPACE, "get", "pvc", PROBE_NAME)
    api = _kubectl_json("-n", "default", "get", "service", "kubernetes")
    grafana = _kubectl_json("-n", "monitoring", "get", "service", "grafana")
    grafana_wait_seconds = min(config["readinessDeadlineSeconds"]["mesh"], 300)
    subprocess.run(
        ["kubectl", "-n", "monitoring", "rollout", "status", "deployment/grafana",
         f"--timeout={grafana_wait_seconds}s"],
        capture_output=True, text=True, timeout=grafana_wait_seconds + 30, check=True)
    grafana_pods = _kubectl_json("-n", "monitoring", "get", "pods", "-l",
                                 "app.kubernetes.io/name=grafana,app.kubernetes.io/instance=grafana")
    volume_name = claim.get("spec", {}).get("volumeName")
    if not isinstance(volume_name, str) or not volume_name:
        raise ValueError("maintenance NFS claim has no bound volume")
    volume = _kubectl_json("get", "pv", volume_name)
    pod_spec = pod.get("spec", {})
    pod_status = pod.get("status", {})
    claim_uid = claim.get("metadata", {}).get("uid")
    pod_uid = pod.get("metadata", {}).get("uid")
    volume_uid = volume.get("metadata", {}).get("uid")
    if (pod_spec.get("nodeName") != PROBE_NODE or
            pod_spec.get("automountServiceAccountToken") is not False or
            pod_status.get("phase") != "Running" or
            not any(item.get("type") == "Ready" and item.get("status") == "True"
                    for item in pod_status.get("conditions", [])) or
            [item.get("image") for item in pod_spec.get("containers", [])] != [PROBE_IMAGE] or
            [item.get("volumeMounts") for item in pod_spec.get("containers", [])] != [[
                {"name": "storage", "mountPath": "/probe"}]] or
            not any(item.get("name") == "storage" and item.get("persistentVolumeClaim", {}).get(
                "claimName") == PROBE_NAME for item in pod_spec.get("volumes", [])) or
            claim.get("status", {}).get("phase") != "Bound" or
            claim.get("spec", {}).get("storageClassName") != "nfs-default" or
            volume.get("status", {}).get("phase") != "Bound" or
            volume.get("spec", {}).get("claimRef", {}).get("uid") != claim_uid or
            volume.get("spec", {}).get("storageClassName") != "nfs-default" or
            volume.get("spec", {}).get("nfs", {}).get("server") != "10.1.0.2" or
            not volume.get("spec", {}).get("nfs", {}).get("path", "").startswith("/homelab/") or
            any(not isinstance(value, str) or not value
                for value in (pod_uid, claim_uid, volume_uid))):
        raise ValueError("maintenance NFS fixture is absent, unready or changed")
    api_ip = api.get("spec", {}).get("clusterIP")
    grafana_ip = grafana.get("spec", {}).get("clusterIP")
    for address in (api_ip, grafana_ip):
        ipaddress.IPv4Address(address)
    selector = {"app.kubernetes.io/name": "grafana", "app.kubernetes.io/instance": "grafana"}
    selected = grafana_pods.get("items")
    if (grafana.get("spec", {}).get("selector") != selector or
            not any(item.get("port") == 80 and item.get("targetPort") == "grafana"
                    for item in grafana.get("spec", {}).get("ports", [])) or
            not isinstance(grafana.get("metadata", {}).get("uid"), str) or
            not grafana["metadata"]["uid"] or
            not isinstance(selected, list) or len(selected) != 1):
        raise ValueError("Grafana Service identity is unavailable or changed")
    grafana_pod = selected[0]
    grafana_name = grafana_pod.get("metadata", {}).get("name")
    grafana_uid = grafana_pod.get("metadata", {}).get("uid")
    if (not isinstance(grafana_name, str) or
            not re.fullmatch(r"grafana-[a-z0-9-]+", grafana_name) or
            not isinstance(grafana_uid, str) or not grafana_uid or
            any(grafana_pod.get("metadata", {}).get("labels", {}).get(key) != value
                for key, value in selector.items()) or
            grafana_pod.get("metadata", {}).get("deletionTimestamp") or
            grafana_pod.get("status", {}).get("phase") != "Running" or
            not any(item.get("type") == "Ready" and item.get("status") == "True"
                    for item in grafana_pod.get("status", {}).get("conditions", [])) or
            not any(container.get("name") == "grafana" and
                    any(port.get("name") == "grafana" and port.get("containerPort") == 3000
                        for port in container.get("ports", []))
                    for container in grafana_pod.get("spec", {}).get("containers", []))):
        raise ValueError("Grafana Pod endpoint is unavailable or changed")
    path_result = subprocess.run(
        ["kubectl", "--request-timeout=15s", "-n", PROBE_NAMESPACE, "exec", "-i",
         PROBE_NAME, "-c", "probe", "--", "/usr/bin/python3", "-", "/probe", api_ip,
         grafana_ip], input=PROBE_SCRIPT.read_text(), capture_output=True, text=True,
        timeout=45, check=True)
    path_evidence = json.loads(path_result.stdout)
    expected_dns = {"kubernetes.default.svc.cluster.local": api_ip,
                    "grafana.monitoring.svc.cluster.local": grafana_ip}
    if path_evidence.get("dns") != expected_dns:
        raise ValueError("in-cluster DNS path differs from Service identity")
    application = _grafana_health_via_port_forward(grafana_name)
    application.update({"service": "monitoring/grafana",
                        "serviceUid": grafana["metadata"]["uid"],
                        "pod": grafana_name, "podUid": grafana_uid})
    raw = subprocess.run(["kubectl", "--request-timeout=15s", "get", "--raw", "/readyz"],
                         capture_output=True, text=True, timeout=25, check=True)
    if raw.stdout.strip() != "ok":
        raise ValueError("Octelium Kubernetes API path failed")
    control = config["expectedStart"]["nodes"]["acer"]["address"]
    talos = subprocess.run(
        ["talosctl", "--talosconfig", str(talosconfig), "--endpoints",
         config["protectedTalosEndpoint"], "--nodes", control, "version", "--short"],
        capture_output=True, text=True, timeout=30, check=True)
    if not re.search(r"Server:\s*Talos v\d+\.\d+\.\d+", talos.stdout):
        raise ValueError("Octelium Talos mTLS path failed")
    webhook_proof = _webhook_path_proof(min(config["readinessDeadlineSeconds"]["mesh"], 300))
    probe = {"format": 1, "sourceSha": source_sha, "stage": stage, "node": node,
             "capturedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "fixture": {"namespace": PROBE_NAMESPACE, "pod": PROBE_NAME,
                         "claim": PROBE_NAME, "storageClass": "nfs-default",
                         "podUid": pod_uid, "claimUid": claim_uid,
                         "volumeUid": volume_uid, "node": pod_spec["nodeName"]},
             "dns": path_evidence["dns"], "storage": path_evidence.get("storage"),
             "application": application,
             "access": {"octeliumKubernetesApi": True, "octeliumTalosMtls": True},
             "webhooks": webhook_proof}
    return verify_path_probe(probe, stage, node, source_sha)


def kubernetes_server_version():
    result = subprocess.run(["kubectl", "version", "-o", "json"],
                            capture_output=True, text=True, timeout=30, check=True)
    version = json.loads(result.stdout).get("serverVersion", {}).get("gitVersion")
    if not isinstance(version, str) or not re.fullmatch(r"v\d+\.\d+\.\d+", version):
        raise ValueError("Kubernetes API server version is unavailable")
    return version.removeprefix("v")


def finish_started_stage(config, stage, source_sha, receipt_dir, path_probe, store=None):
    path = private_output(receipt_dir / f"{stage}.json")
    pending = read_private_json(path)
    if (not isinstance(pending, dict) or pending.get("stage") != stage or
            pending.get("sourceSha") != source_sha or pending.get("status") != "started" or
            pending.get("verified") is not False):
        raise ValueError("platform stage is not in a known pending state")
    record = {"format": 1, "stage": stage, "sourceSha": source_sha,
              "verified": True, "pathProbe": path_probe, "nodes": {
                  node: hashlib.sha256(node_receipt_path(receipt_dir, stage, node).read_bytes()).hexdigest()
                  for node in NODES}}
    verify_stage_receipt(config, stage, record, receipt_dir)
    temporary = path.with_name(f".{path.name}.complete")
    save_inspection(temporary, record)
    os.replace(temporary, path)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    if store is not None:
        store.write(stage, None, "verified", path)
    return record


def protected_context(source_sha):
    if (os.environ.get("GITHUB_ACTIONS") != "true" or
            os.environ.get("GITHUB_REF") != "refs/heads/main" or
            os.environ.get("GITHUB_SHA") != source_sha):
        raise ValueError("maintenance requires protected current-main workflow context")


def require_reviewed_execution_config(path, source_sha):
    """Reject an uncommitted activation or canary override before any upgrade checks."""
    canonical = ROOT / "scripts/config/platform-maintenance.json"
    if (not isinstance(source_sha, str) or not SHA.fullmatch(source_sha) or
            path.resolve() != canonical.resolve()):
        raise ValueError("platform execution config path is not repository-owned")
    try:
        committed = subprocess.check_output(
            ["git", "--no-replace-objects", "show",
             f"{source_sha}:scripts/config/platform-maintenance.json"],
            cwd=ROOT, timeout=15)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ValueError("reviewed platform execution config is unavailable") from None
    if canonical.read_bytes() != committed:
        raise ValueError("platform execution config differs from exact reviewed commit")
    return committed


def require_publication(config, source_sha, receipt):
    talos = {f"talos-{item['to']}": item["installerImage"]
             for item in config["talosStages"]}
    if (not isinstance(receipt, dict) or receipt.get("sourceSha") != source_sha or
            receipt.get("verified") is not True or
            receipt.get("talosImages") != talos or
            receipt.get("kubernetesImages") != config["kubernetesStage"]["images"]):
        raise ValueError("platform image publication receipt is incomplete")


def execute_talos_stage(config, stage, source_sha, talosconfig, receipt_dir, store=None):
    protected_context(source_sha)
    if store is not None:
        store.restore(stage, receipt_dir)
    target = next((item for item in config["talosStages"]
                   if stage == f"talos-{item['to']}"), None)
    if target is None:
        raise ValueError("only reviewed Talos stages use node upgrade execution")
    receipts = read_receipts(receipt_dir)
    verify_prerequisites(config, source_sha, receipts)
    require_publication(config, source_sha, receipts.get("artifact-publication"))
    observed = read_only_inspection(config, talosconfig)
    stage_file = private_output(receipt_dir / f"{stage}.json")
    if stage_file.exists():
        complete = verify_stage_receipt(
            config, stage, read_private_json(stage_file), receipt_dir)
        if (complete.get("sourceSha") != source_sha or
                any(observed["nodes"][node]["talos"] != target["to"] for node in NODES)):
            raise ValueError("existing stage receipt does not match live target")
        cluster_health(config, talosconfig)
        inter_node_path_probe(config, talosconfig, stage, "stage", source_sha)
        return complete
    for node in NODES:
        current = observed["nodes"][node]
        node_action(node, target["from"], target["to"], current["talos"], current["bootID"],
                    read_node_receipt(receipt_dir, stage, node), source_sha, stage)
        if not current["ready"] or current["kubelet"] != "v1.34.11":
            raise ValueError("node or Kubernetes baseline is not healthy")
    for node in NODES:
        current = observed["nodes"][node]
        receipt = read_node_receipt(receipt_dir, stage, node)
        action = node_action(node, target["from"], target["to"], current["talos"],
                             current["bootID"], receipt, source_sha, stage)
        if not current["ready"] or current["kubelet"] != "v1.34.11":
            raise ValueError("node or Kubernetes baseline is not healthy")
        cluster_health(config, talosconfig)
        inter_node_path_probe(config, talosconfig, stage, node, source_sha)
        if action == "skip":
            continue
        if current_main_sha() != source_sha:
            raise ValueError("main advanced before Talos node upgrade")
        verify_prerequisites(config, source_sha, read_receipts(receipt_dir))
        machine_before = active_machine_state(config, talosconfig, node)
        verify_installer_mirror_route(machine_before, target["installerImage"])
        start_node_receipt(receipt_dir, stage, node, target["from"], target["to"], source_sha,
                           store)
        if current_main_sha() != source_sha:
            raise ValueError("main advanced after Talos node start receipt")
        subprocess.run(talos_upgrade_command(config, stage, node, talosconfig),
                       capture_output=True, text=True,
                       timeout=config["readinessDeadlineSeconds"]["node"] + 60,
                       check=True)
        observed = read_only_inspection(config, talosconfig)
        current = observed["nodes"][node]
        if active_machine_state(config, talosconfig, node) != machine_before:
            raise ValueError("Talos upgrade changed machine role, install disk, or mirror map")
        if (current["talos"] != target["to"] or not current["ready"] or
                current["kubelet"] != "v1.34.11"):
            raise ValueError("Talos node did not reach the reviewed target")
        cluster_health(config, talosconfig)
        path_probe = inter_node_path_probe(config, talosconfig, stage, node, source_sha)
        complete_node_receipt(receipt_dir, stage, node, source_sha, {
            "observedVersion": current["talos"], "ready": True,
            "clusterHealth": True, "bootID": current["bootID"], "pathProbe": path_probe,
        }, store)
    if current_main_sha() != source_sha:
        raise ValueError("main advanced before Talos stage completion")
    if any(observed["nodes"][node]["talos"] != target["to"] for node in NODES):
        raise ValueError("Talos stage has an unupgraded node")
    cluster_health(config, talosconfig)
    stage_probe = inter_node_path_probe(config, talosconfig, stage, "stage", source_sha)
    if current_main_sha() != source_sha:
        raise ValueError("main advanced before Talos stage receipt")
    stage_receipt = {"format": 1, "stage": stage, "sourceSha": source_sha,
                     "verified": True, "pathProbe": stage_probe, "nodes": {
                         node: hashlib.sha256(node_receipt_path(receipt_dir, stage, node).read_bytes()).hexdigest()
                         for node in NODES}}
    verify_stage_receipt(config, stage, stage_receipt, receipt_dir)
    save_inspection(stage_file, stage_receipt)
    if store is not None:
        store.write(stage, None, "verified", stage_file)
    return stage_receipt


def execute_kubernetes_stage(config, stage, source_sha, talosconfig, receipt_dir, store=None):
    protected_context(source_sha)
    if store is not None:
        store.restore(stage, receipt_dir)
    target = config["kubernetesStage"]
    if stage != f"kubernetes-{target['to']}":
        raise ValueError("unreviewed Kubernetes upgrade stage")
    receipts = read_receipts(receipt_dir)
    verify_prerequisites(config, source_sha, receipts)
    require_publication(config, source_sha, receipts.get("artifact-publication"))
    catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
    command = kubernetes_upgrade_command(config, talosconfig, catalog)
    observed = read_only_inspection(config, talosconfig)
    current_version = kubernetes_server_version()
    stage_file = private_output(receipt_dir / f"{stage}.json")
    if stage_file.exists():
        complete = verify_stage_receipt(config, stage, read_private_json(stage_file), receipt_dir)
        if (complete.get("sourceSha") != source_sha or current_version != target["to"] or
                any(observed["nodes"][node]["kubelet"] != f"v{target['to']}"
                    for node in NODES)):
            raise ValueError("existing Kubernetes receipt does not match live target")
        cluster_health(config, talosconfig)
        verify_live_istio_target(config)
        inter_node_path_probe(config, talosconfig, stage, "stage", source_sha)
        return complete
    if (current_version != target["from"] or
            any(observed["nodes"][node]["talos"] != config["talosStages"][-1]["to"] or
                observed["nodes"][node]["kubelet"] != f"v{target['from']}" or
                not observed["nodes"][node]["ready"] for node in NODES)):
        raise ValueError("Kubernetes upgrade baseline is not uniformly ready")
    cluster_health(config, talosconfig)
    inter_node_path_probe(config, talosconfig, stage, "stage", source_sha)
    verify_live_istio_target(config)
    verify_kubernetes_mirror_routes(config, talosconfig)
    verify_kubernetes_mirror_tags(config)
    if current_main_sha() != source_sha:
        raise ValueError("main advanced before Kubernetes upgrade")
    save_inspection(stage_file, {"format": 1, "stage": stage, "sourceSha": source_sha,
                                 "from": target["from"], "to": target["to"],
                                 "verified": False, "status": "started"})
    if store is not None:
        store.write(stage, None, "started", stage_file)
    if current_main_sha() != source_sha:
        raise ValueError("main advanced after Kubernetes start receipt")
    subprocess.run(command, capture_output=True, text=True,
                   timeout=len(NODES) * config["readinessDeadlineSeconds"]["node"] + 300,
                   check=True)
    observed = read_only_inspection(config, talosconfig)
    if (kubernetes_server_version() != target["to"] or
            any(observed["nodes"][node]["talos"] != config["talosStages"][-1]["to"] or
                observed["nodes"][node]["kubelet"] != f"v{target['to']}" or
                not observed["nodes"][node]["ready"] for node in NODES)):
        raise ValueError("Kubernetes upgrade did not reach every reviewed target")
    cluster_health(config, talosconfig)
    verify_live_istio_target(config)
    if current_main_sha() != source_sha:
        raise ValueError("main advanced before Kubernetes stage verification")
    for node in NODES:
        path_probe = inter_node_path_probe(config, talosconfig, stage, node, source_sha)
        start_node_receipt(receipt_dir, stage, node, target["from"], target["to"], source_sha,
                           store)
        complete_node_receipt(receipt_dir, stage, node, source_sha, {
            "observedVersion": target["to"], "ready": True, "clusterHealth": True,
            "bootID": observed["nodes"][node]["bootID"], "pathProbe": path_probe,
        }, store)
    stage_probe = inter_node_path_probe(config, talosconfig, stage, "stage", source_sha)
    if current_main_sha() != source_sha:
        raise ValueError("main advanced before Kubernetes stage receipt")
    return finish_started_stage(config, stage, source_sha, receipt_dir, stage_probe, store)


def read_only_inspection(config, talosconfig):
    if (not talosconfig.is_file() or talosconfig.stat().st_size == 0 or
            talosconfig.stat().st_uid != os.getuid() or
            stat.S_IMODE(talosconfig.stat().st_mode) != 0o600):
        raise ValueError("authenticated Talos client config is missing")
    result = subprocess.run(["kubectl", "get", "nodes", "-o", "json"],
                            capture_output=True, text=True, timeout=60, check=True)
    nodes = json.loads(result.stdout).get("items")
    if (not isinstance(nodes, list) or len(nodes) != len(NODES) or
            {item.get("metadata", {}).get("name") for item in nodes} != set(NODES)):
        raise ValueError("live Kubernetes node identities differ from reviewed input")
    observed = {}
    for node, address in zip(NODES, ADDRESSES):
        item = next(item for item in nodes if item["metadata"]["name"] == node)
        status = item.get("status", {})
        if address not in [entry.get("address") for entry in status.get("addresses", [])]:
            raise ValueError("live node address differs from reviewed input")
        talos = subprocess.run(
            ["talosctl", "--talosconfig", str(talosconfig), "--endpoints",
             config["protectedTalosEndpoint"],
             "--nodes", address, "version", "--short"],
            capture_output=True, text=True, timeout=30, check=True)
        versions = re.findall(r"Talos v(\d+\.\d+\.\d+)", talos.stdout)
        if len(versions) < 2:
            raise ValueError("Talos server version is unavailable")
        extensions = subprocess.run(
            ["talosctl", "--talosconfig", str(talosconfig), "--endpoints",
             config["protectedTalosEndpoint"],
             "--nodes", address, "get", "extensionstatus", "-o", "json"],
            capture_output=True, text=True, timeout=30, check=True)
        value = extensions.stdout.strip()
        if value and json.loads(value) not in ([], {"items": []}):
            raise ValueError("Talos node has extensions requiring a reviewed schematic")
        observed[node] = {
            "address": address,
            "talos": versions[-1],
            "kubelet": status.get("nodeInfo", {}).get("kubeletVersion"),
            "osImage": status.get("nodeInfo", {}).get("osImage"),
            "bootID": status.get("nodeInfo", {}).get("bootID"),
            "extensions": 0,
            "ready": any(condition.get("type") == "Ready" and condition.get("status") == "True"
                         for condition in status.get("conditions", [])),
            "capacity": status.get("capacity", {}),
            "allocatable": status.get("allocatable", {}),
        }
    return {"format": 1, "status": "observed-only",
            "capturedAt": datetime.now(timezone.utc).isoformat(),
            "nodes": observed}


def save_inspection(path, record):
    path = private_output(path)
    content = json.dumps(record, sort_keys=True, indent=2) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def validate_rendered_configs(config, control_plane, worker):
    """Strictly validate private bases and every reviewed offline target patch."""
    validate_target_patches(config)
    for path in (control_plane, worker):
        if (not path.is_file() or path.stat().st_uid != os.getuid() or
                stat.S_IMODE(path.stat().st_mode) != 0o600):
            raise ValueError("private machine configuration is missing or not mode 0600")
    with tempfile.TemporaryDirectory(prefix="platform-config-", dir="/tmp") as directory:
        for role, base in (("controlPlane", control_plane), ("worker", worker)):
            subprocess.run(["talosctl", "validate", "--config", str(base),
                            "--mode", "metal", "--strict"],
                           capture_output=True, text=True, timeout=60, check=True)
            patches = [ROOT / f'.talos/patches/talos-{stage["to"]}.yaml'
                       for stage in config["talosStages"]]
            patches.append(ROOT / config["kubernetesStage"]["offlineRenderPatches"][role])
            for index, patch in enumerate(patches):
                if not patch.is_file():
                    raise ValueError("reviewed machine configuration patch is missing")
                rendered = subprocess.run(
                    ["talosctl", "machineconfig", "patch", str(base), "--patch", f"@{patch}"],
                    capture_output=True, text=True, timeout=60, check=True,
                ).stdout
                if not rendered:
                    raise ValueError("machine configuration patch rendered empty output")
                destination = Path(directory) / f"{role}-{index}.yaml"
                fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as output:
                    output.write(rendered)
                subprocess.run(["talosctl", "validate", "--config", str(destination),
                                "--mode", "metal", "--strict"],
                               capture_output=True, text=True, timeout=60, check=True)


def validate_target_patches(config):
    """Image-only OS patches preserve each private base's install disk."""
    def lines(path):
        return [line.rstrip() for line in path.read_text().splitlines()
                if line.strip() and not line.lstrip().startswith("#")]

    for stage in config["talosStages"]:
        patch = ROOT / f'.talos/patches/talos-{stage["to"]}.yaml'
        if lines(patch) != ["machine:", "  install:",
                            f'    image: {stage["installerImage"]}']:
            raise ValueError("Talos target patch changes more than the pinned installer image")
    target = config["kubernetesStage"]
    images = {component: source.split("@sha256:", 1)[0]
              for component, source in target["images"].items()}
    worker = ROOT / target["offlineRenderPatches"]["worker"]
    control = ROOT / target["offlineRenderPatches"]["controlPlane"]
    kubelet = ["machine:", "  kubelet:", f'    image: {images["kubelet"]}']
    if lines(worker) != kubelet:
        raise ValueError("worker target patch changes more than the pinned kubelet image")
    expected_control = kubelet + ["cluster:", "  apiServer:",
        f'    image: {images["kube-apiserver"]}', "  controllerManager:",
        f'    image: {images["kube-controller-manager"]}', "  scheduler:",
        f'    image: {images["kube-scheduler"]}', "  proxy:",
        f'    image: {images["kube-proxy"]}']
    if lines(control) != expected_control:
        raise ValueError("control-plane target patch differs from pinned Kubernetes images")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "validate", "execute"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--talosconfig", type=Path, default=ROOT / ".talos/talosconfig")
    parser.add_argument("--control-plane-config", type=Path)
    parser.add_argument("--worker-config", type=Path)
    parser.add_argument("--receipt-dir", type=Path)
    parser.add_argument("--stage")
    parser.add_argument("--expected-sha")
    args = parser.parse_args()
    try:
        if args.command == "execute":
            protected_context(args.expected_sha)
            config_bytes = require_reviewed_execution_config(args.config, args.expected_sha)
        else:
            config_bytes = args.config.read_bytes()
        config = validate_config(json.loads(config_bytes))
        if args.command == "inspect":
            output = private_output(args.output)
            save_inspection(output, read_only_inspection(config, args.talosconfig))
            print("Private platform inspection captured")
            return 0
        if args.command == "validate":
            if (args.control_plane_config is None) != (args.worker_config is None):
                raise ValueError("both private role-specific Talos configurations are required")
            if args.control_plane_config is None:
                print("Pinned platform declaration validated only; private Talos configurations, recovery, and live readiness unverified")
            else:
                validate_rendered_configs(config, args.control_plane_config, args.worker_config)
                print("Pinned platform declaration and private Talos configurations validated offline; recovery and live readiness unverified")
            return 0
        if args.control_plane_config is None or args.worker_config is None:
            raise ValueError("private role-specific Talos configurations are required")
        validate_rendered_configs(config, args.control_plane_config, args.worker_config)
        if args.stage is None or args.expected_sha is None or args.receipt_dir is None:
            raise ValueError("reviewed stage, current SHA and private receipts are required")
        store = None
        if args.command == "execute":
            protected_context(args.expected_sha)
            if current_main_sha() != args.expected_sha:
                raise ValueError("main advanced before durable platform receipt access")
            if not config["activationEnabled"] or config["canary"]["node"] is None:
                raise ValueError("platform maintenance is not activated")
            store = DurableReceipts(receipt_target())
            store.check()
            store.load_prerequisites(args.expected_sha, args.receipt_dir)
            if args.stage.startswith("kubernetes-"):
                store.load_istio_completions(config, args.receipt_dir)
            for item in config["talosStages"]:
                prior = f"talos-{item['to']}"
                if prior == args.stage:
                    break
                store.restore(prior, args.receipt_dir)
        receipts = read_receipts(args.receipt_dir)
        authorize_stage(config, args.stage, args.expected_sha,
                        current_main_sha(), receipts)
        for item in config["talosStages"]:
            prior = f"talos-{item['to']}"
            if prior == args.stage:
                break
            verify_stage_receipt(config, prior, receipts[prior], args.receipt_dir)
        if args.command == "execute":
            if args.stage.startswith("talos-"):
                execute_talos_stage(config, args.stage, args.expected_sha,
                                    args.talosconfig, args.receipt_dir, store)
            elif args.stage.startswith("kubernetes-"):
                execute_kubernetes_stage(config, args.stage, args.expected_sha,
                                         args.talosconfig, args.receipt_dir, store)
            else:
                raise ValueError("Istio stages use separately reviewed GitOps changes")
            print("Reviewed platform stage verified; private receipt retained")
            return 0
        print("Platform maintenance preflight passed; no live state changed")
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        if args.output is not None:
            try:
                save_inspection(args.output, {
                    "format": 1, "status": "failed", "phase": args.command,
                    "error": str(error),
                    "stdout": getattr(error, "stdout", None),
                    "stderr": getattr(error, "stderr", None),
                })
            except (OSError, ValueError, TypeError):
                # A failed diagnostic write must not hide the stage failure.
                pass
        print("Platform maintenance blocked; inspect private diagnostics", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
