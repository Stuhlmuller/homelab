#!/usr/bin/env python3
"""Protected, one-component Istio apply admission and post-sync receipt publisher.

The phase source is inert at zero. An active phase needs a protected targeted
Terragrunt apply, followed by a separate protected Platform Maintenance verify.
An interrupted apply has a durable start marker and can only be verified or
recovered through another reviewed source change; it cannot silently reapply.
"""

import argparse
import base64
import binascii
import copy
import hashlib
import http.client
import importlib.util
import json
import os
import re
import select
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGE = "istio-1.28.10"
SOURCE_FILES = (
    "scripts/istio-upgrade.py", "scripts/ci/istio-upgrade-gate.py",
    "scripts/ci/istio-prior-run-check.py", "scripts/platform-maintenance.py",
    "scripts/ci/platform-maintenance-pod-probe.py",
    "scripts/config/platform-maintenance.json",
    "clusters/homelab/apps/istio/upgrade-1.28.10.json",
    "clusters/homelab/apps/istio/upgrade-1.28.10/istiod-images.json",
    "clusters/homelab/apps/istio/upgrade-1.28.10/istiod-final-images.json",
    "clusters/homelab/apps/istio/upgrade-1.28.10/cni-images.json",
    "clusters/homelab/apps/istio/upgrade-1.28.10/ztunnel-images.json",
    "clusters/homelab/apps/istio/upgrade-1.28.10/gateway-images.json",
    "IaC/homelab/us-west-2/apps/istio/stack.hcl",
    ".github/workflows/platform-maintenance.yml",
    ".github/workflows/terragrunt-apply.yml",
)
CRDS = (
    "authorizationpolicies.security.istio.io", "destinationrules.networking.istio.io",
    "envoyfilters.networking.istio.io", "gateways.networking.istio.io",
    "peerauthentications.security.istio.io", "proxyconfigs.networking.istio.io",
    "requestauthentications.security.istio.io", "serviceentries.networking.istio.io",
    "sidecars.networking.istio.io", "telemetries.telemetry.istio.io",
    "virtualservices.networking.istio.io", "wasmplugins.extensions.istio.io",
    "workloadentries.networking.istio.io", "workloadgroups.networking.istio.io",
)
WEBHOOKS = (
    ("validatingwebhookconfiguration", "istio-validator-istio-system"),
    ("validatingwebhookconfiguration", "istiod-default-validator"),
    ("mutatingwebhookconfiguration", "istio-sidecar-injector"),
)
WORKLOADS = (
    ("Deployment", "istiod", "pilot"),
    ("DaemonSet", "istio-cni-node", "install-cni"),
    ("DaemonSet", "ztunnel", "ztunnel"),
    ("Deployment", "istio-ingressgateway", "proxyv2"),
    ("Deployment", "octelium-api-ingressgateway", "proxyv2"),
)
OLD_PROXY_IMAGE = "docker.io/istio/proxyv2@sha256:0ff2299890e3e5b9fe0e38391b048c0788900f69af27306a7aef3036a59220e1"
OLD_IMAGE_DIGESTS = {
    "pilot": "70f4f8ccf75ba51187f0920b3f40a6517ba98c068b1b88399a342cbd5e31b857",
    "install-cni": "cfe35258547be35aed2f3c94b56949d5460c0dd3810b94a16d3310c7e9337e62",
    "ztunnel": "3837029816e78cb6fc88d928dc5c6c58522ab9346772a1409b7f7da00d9de4ce",
    "proxyv2": OLD_PROXY_IMAGE.rsplit(":", 1)[1],
}


def digest_image(reference):
    require(isinstance(reference, str) and re.fullmatch(
        r"docker\.io/istio/[a-z0-9-]+:1\.28\.10-distroless@sha256:[0-9a-f]{64}",
        reference), "reviewed Istio image reference is invalid")
    repository, image_digest = reference.split("@sha256:")
    return repository.split(":", 1)[0] + "@sha256:" + image_digest


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLAT = load_module("platform_maintenance", "scripts/platform-maintenance.py")
GATE = load_module("istio_gate", "scripts/ci/istio-upgrade-gate.py")
RUNS = load_module("istio_runs", "scripts/ci/istio-prior-run-check.py")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def command(*args, timeout=30):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          timeout=timeout, check=True).stdout


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def source_bundle():
    return digest({path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                   for path in SOURCE_FILES})


def source_bundle_at(revision):
    require(isinstance(revision, str) and PLAT.SHA.fullmatch(revision),
            "unreviewed Istio source bundle revision")
    values = {}
    for path in SOURCE_FILES:
        result = subprocess.run(["git", "show", f"{revision}:{path}"], cwd=ROOT,
                                capture_output=True, timeout=30, check=True)
        values[path] = hashlib.sha256(result.stdout).hexdigest()
    return digest(values)


def candidate_at(revision):
    require(PLAT.SHA.fullmatch(revision), "unreviewed candidate revision")
    return json.loads(command("git", "show", f"{revision}:{RUNS.CANDIDATE}"))


def protected_source(source_sha):
    PLAT.protected_context(source_sha)
    require(PLAT.current_main_sha() == source_sha,
            "main advanced before Istio operation")
    candidate = json.loads(GATE.CANDIDATE.read_text())
    phase = GATE.check_candidate(candidate)
    require(phase > 0 and candidate == candidate_at(source_sha),
            "Istio phase differs from reviewed current main")
    config_path = ROOT / "scripts/config/platform-maintenance.json"
    PLAT.require_reviewed_execution_config(config_path, source_sha)
    config = PLAT.validate_config(json.loads(config_path.read_text()))
    require(config["activationEnabled"] and config["canary"]["node"] is not None,
            "platform canary and maintenance activation are held")
    return candidate, config, phase


def public_runs(candidate, source_sha):
    def ancestor(revision):
        return subprocess.run(
            ["git", "merge-base", "--is-ancestor", revision, source_sha],
            cwd=ROOT, capture_output=True, timeout=15).returncode == 0

    def fetch_run(identifier):
        require(isinstance(identifier, str) and
                re.fullmatch(r"[1-9][0-9]{0,18}", identifier), "invalid protected run ID")
        run = json.loads(command("gh", "api", f"repos/{RUNS.REPOSITORY}/actions/runs/{identifier}"))
        if run.get("path") in (".github/workflows/harbor-mirror.yml",
                               ".github/workflows/harbor-helm-charts.yml"):
            jobs = json.loads(command("gh", "api", f"repos/{RUNS.REPOSITORY}/actions/runs/{identifier}/jobs"))
            require(jobs.get("total_count") == 2, "Harbor job inventory is incomplete")
            run["jobs"] = jobs.get("jobs")
        return run

    def bundle_equal(paths, revision):
        return all(command("git", "rev-parse", f"{revision}:{path}") ==
                   command("git", "rev-parse", f"{source_sha}:{path}")
                   for path in paths)

    RUNS.verify_runs(
        candidate, fetch_run, ancestor, candidate_at,
        lambda revision: bundle_equal(RUNS.PUBLICATION_BUNDLE, revision),
        lambda revision: bundle_equal(RUNS.CHART_PUBLICATION_BUNDLE, revision))
    return fetch_run(candidate["priorRunId"])


def chart_publication_run(candidate):
    run_id = candidate["chartRunId"]
    run = json.loads(command("gh", "api",
                             f"repos/{RUNS.REPOSITORY}/actions/runs/{run_id}"))
    revision, attempt = run.get("head_sha"), run.get("run_attempt")
    require(run.get("id") == int(run_id) and isinstance(revision, str) and
            PLAT.SHA.fullmatch(revision) and type(attempt) is int and attempt >= 1 and
            run.get("name") == f"Helm charts @ {revision}" and
            run.get("display_title") == f"Helm charts @ {revision}" and
            run.get("path") == ".github/workflows/harbor-helm-charts.yml" and
            run.get("event") == "workflow_dispatch" and
            run.get("head_branch") == "main" and
            run.get("status") == "completed" and run.get("conclusion") == "success",
            "Istio chart publication run is incomplete")
    return run


def validate_chart_receipt(candidate, run, receipt):
    revision = run["head_sha"]
    pins = {chart: archive for chart, _, archive in GATE.COMPONENTS}
    rows = receipt.get("charts") if isinstance(receipt, dict) else None
    require(isinstance(receipt, dict) and
            set(receipt) == {"sourceSha", "destination", "charts"} and
            receipt["sourceSha"] == revision and
            receipt["destination"] == "harbor.stinkyboi.com/mirror/helm" and
            isinstance(rows, list) and len(rows) == len(pins),
            "Istio chart publication receipt is incomplete")
    found = {}
    for row in rows:
        require(isinstance(row, dict) and
                set(row) == {"chart", "version", "packageSha256", "manifestDigest"} and
                row.get("chart") in pins and row["chart"] not in found and
                row.get("version") == "1.28.10" and
                row.get("packageSha256") == pins[row["chart"]] and
                row.get("manifestDigest") == candidate["chartManifestDigests"][row["chart"]],
                "Istio chart package or OCI digest differs from reader receipt")
        found[row["chart"]] = row["manifestDigest"]
    require(set(found) == set(pins), "Istio chart reader receipt omits a package")
    return receipt


def chart_publication_receipt(candidate):
    """Bind the protected Harbor reader pullback to every immutable OCI source."""
    run = chart_publication_run(candidate)
    run_id = candidate["chartRunId"]
    revision, attempt = run["head_sha"], run["run_attempt"]
    artifact_name = f"harbor-istio-charts-{revision}-{run_id}-{attempt}"
    with tempfile.TemporaryDirectory(prefix="istio-chart-proof-") as directory:
        command("gh", "run", "download", run_id, "--repo", RUNS.REPOSITORY,
                "--name", artifact_name, "--dir", directory, timeout=90)
        files = list(Path(directory).rglob("*"))
        require(len(files) == 1 and files[0].is_file() and
                files[0].name == "harbor-istio-charts-receipt.json" and
                files[0].stat().st_size <= 16384,
                "Istio chart reader receipt artifact is missing or ambiguous")
        receipt = json.loads(files[0].read_text())
    validate_chart_receipt(candidate, run, receipt)
    harbor_chart_readback(receipt)
    return receipt


def saved_chart_publication_receipt(started, current_candidate):
    original = candidate_at(started["sourceSha"])
    GATE.check_candidate(original)
    require(original["chartManifestDigests"] == current_candidate["chartManifestDigests"],
            "Istio chart digest set changed after protected apply")
    run = chart_publication_run(original)
    receipt = validate_chart_receipt(original, run, started["chartReceipt"])
    require(digest(receipt) == started["chartReceiptSha256"],
            "Istio saved chart publication receipt changed")
    harbor_chart_readback(receipt)
    return receipt


def harbor_chart_readback(receipt):
    """Read the immutable OCI manifest and Helm layer through private Harbor TLS."""
    password = command("aws", "ssm", "get-parameter", "--region", "us-west-2",
                       "--name", "/homelab/harbor/mirror-robot-pull-password",
                       "--with-decryption", "--query", "Parameter.Value", "--output", "text").strip()
    require(password and password != "None", "Harbor chart reader credential is missing")
    argo_oci_credential_proof(password)
    process, port = port_forward("traefik", "service/traefik-private", 443)
    try:
        context = ssl.create_default_context()

        class LocalHTTPS(http.client.HTTPSConnection):
            def connect(self):
                raw = self._create_connection(("127.0.0.1", port), self.timeout)
                self.sock = self._context.wrap_socket(raw, server_hostname=self.host)

        def get(path, headers, limit):
            connection = LocalHTTPS("harbor.stinkyboi.com", timeout=15, context=context)
            try:
                connection.request("GET", path, headers=headers)
                response = connection.getresponse()
                body = response.read(limit + 1)
                require(len(body) <= limit, "Harbor chart readback is unbounded")
                return response.status, dict(response.getheaders()), body
            finally:
                connection.close()

        for row in receipt["charts"]:
            chart = row["chart"]
            manifest_path = (f"/v2/mirror/helm/{chart}/manifests/"
                             f"{row['manifestDigest']}")
            accept = {"Accept": "application/vnd.oci.image.manifest.v1+json"}
            status, headers, _ = get(manifest_path, accept, 4096)
            require(status == 401, "Harbor chart reader challenge is missing")
            challenge = headers.get("www-authenticate", headers.get("WWW-Authenticate", ""))
            fields = dict(re.findall(r'(realm|service|scope)="([^"]+)"', challenge))
            realm = urllib.parse.urlsplit(fields.get("realm", ""))
            require(challenge.startswith("Bearer ") and
                    realm.scheme == "https" and realm.netloc == "harbor.stinkyboi.com" and
                    realm.path == "/service/token" and
                    fields.get("scope") == f"repository:mirror/helm/{chart}:pull" and
                    fields.get("service"),
                    "Harbor chart reader scope changed")
            query = urllib.parse.urlencode({"service": fields["service"],
                                            "scope": fields["scope"]})
            basic = base64.b64encode(("robot$mirror+pull:" + password).encode()).decode()
            token_status, _, token_body = get(realm.path + "?" + query,
                                              {"Authorization": "Basic " + basic}, 8192)
            require(token_status == 200, "Harbor chart reader token failed")
            token = json.loads(token_body).get("token")
            require(isinstance(token, str) and token,
                    "Harbor chart reader token is invalid")
            authorization = {**accept, "Authorization": "Bearer " + token}
            manifest_status, manifest_headers, manifest = get(
                manifest_path, authorization, 1048576)
            require(manifest_status == 200 and
                    hashlib.sha256(manifest).hexdigest() == row["manifestDigest"][7:] and
                    manifest_headers.get("Docker-Content-Digest", row["manifestDigest"]) ==
                    row["manifestDigest"],
                    "Harbor immutable chart manifest differs from publication receipt")
            data = json.loads(manifest)
            layers = data.get("layers") if isinstance(data, dict) else None
            require(isinstance(layers, list) and len(layers) == 1 and
                    layers[0].get("mediaType") ==
                    "application/vnd.cncf.helm.chart.content.v1.tar+gzip" and
                    layers[0].get("digest") == "sha256:" + row["packageSha256"],
                    "Harbor immutable chart layer differs from reviewed archive")
            blob_status, _, blob = get(
                f"/v2/mirror/helm/{chart}/blobs/sha256:{row['packageSha256']}",
                {"Authorization": "Bearer " + token}, 33554432)
            require(blob_status == 200 and
                    hashlib.sha256(blob).hexdigest() == row["packageSha256"],
                    "Harbor chart archive pullback differs from reviewed bytes")
    finally:
        stop_forward(process)


def argo_oci_credential_proof(reader_password):
    """Prove Argo's repo-creds ExternalSecret has reconciled the same reader."""
    name = "argocd-harbor-istio-oci"
    external = PLAT._kubectl_json("-n", "argocd", "get", "externalsecret", name)
    meta, spec, status = (external.get("metadata", {}), external.get("spec", {}),
                          external.get("status", {}))
    template = spec.get("target", {}).get("template", {})
    require(meta.get("uid") and type(meta.get("generation")) is int and
            not meta.get("deletionTimestamp") and
            str(status.get("syncedResourceVersion", "")).startswith(
                str(meta["generation"]) + "-") and
            any(item.get("type") == "Ready" and item.get("status") == "True"
                for item in status.get("conditions", [])) and
            spec.get("secretStoreRef") == {"kind": "ClusterSecretStore", "name": "aws-ssm"} and
            spec.get("target", {}).get("name") == name and
            spec["target"].get("creationPolicy") == "Owner" and
            template.get("type") == "Opaque" and
            template.get("metadata", {}).get("labels", {}).get(
                "argocd.argoproj.io/secret-type") == "repo-creds" and
            template.get("data") == {
                "url": GATE.NEW_REPOSITORY, "type": "oci", "project": "homelab",
                "username": "robot$mirror+pull", "password": "{{ .password }}"} and
            spec.get("data") == [{"secretKey": "password", "remoteRef": {
                "key": "/homelab/harbor/mirror-robot-pull-password",
                "conversionStrategy": "Default", "decodingStrategy": "None",
                "metadataPolicy": "None"}}],
            "Argo Istio OCI reader ExternalSecret is unready or changed")
    secret = PLAT._kubectl_json("-n", "argocd", "get", "secret", name)
    secret_meta = secret.get("metadata", {})
    values = secret.get("data", {})
    require(secret_meta.get("uid") and not secret_meta.get("deletionTimestamp") and
            any(item.get("uid") == meta["uid"] and item.get("kind") == "ExternalSecret"
                for item in secret_meta.get("ownerReferences", [])) and
            secret_meta.get("labels", {}).get("argocd.argoproj.io/secret-type") ==
            "repo-creds" and secret.get("type") == "Opaque" and
            isinstance(values, dict) and
            set(values) == {"url", "type", "project", "username", "password"},
            "Argo Istio OCI repository Secret is missing or changed")
    try:
        decoded = {key: base64.b64decode(value, validate=True).decode()
                   for key, value in values.items()}
    except (ValueError, binascii.Error, UnicodeDecodeError, TypeError):
        raise ValueError("Argo Istio OCI repository Secret is invalid") from None
    require(decoded == {"url": GATE.NEW_REPOSITORY, "type": "oci",
                        "project": "homelab", "username": "robot$mirror+pull",
                        "password": reader_password},
            "Argo Istio OCI repository Secret differs from the protected reader")


class Receipts:
    """One exact version per key; readback uses S3's SHA-256 and KMS metadata."""

    def __init__(self, directory):
        self.directory = PLAT.private_directory(directory)
        self.store = PLAT.DurableReceipts(PLAT.receipt_target())
        self.store.check()

    @staticmethod
    def key(phase, status):
        require(type(phase) is int and 1 <= phase <= 6 and
                status in ("started", "verified"), "unreviewed Istio receipt identity")
        return f"openclaw-enterprise/platform/istio/1.28.10/components/phase-{phase}/{status}.json"

    @staticmethod
    def attempt_key(phase, run_id, status):
        require(type(phase) is int and 1 <= phase <= 6 and
                isinstance(run_id, str) and re.fullmatch(r"[1-9][0-9]*", run_id) and
                status in ("started", "aborted"), "unreviewed Istio attempt identity")
        return ("openclaw-enterprise/platform/istio/1.28.10/components/"
                f"phase-{phase}/attempts/{run_id}/{status}.json")

    @staticmethod
    def attestation_key(phase, run_id):
        require(type(phase) is int and 1 <= phase <= 6 and
                isinstance(run_id, str) and re.fullmatch(r"[1-9][0-9]*", run_id),
                "unreviewed Istio attestation identity")
        return ("openclaw-enterprise/platform/istio/1.28.10/components/"
                f"phase-{phase}/attestations/{run_id}.json")

    def version(self, key):
        result = self.store.call("s3api", "list-object-versions",
                                 ["--prefix", key, "--no-paginate"])
        require(result.get("IsTruncated") is False and not result.get("DeleteMarkers"),
                "Istio receipt history is incomplete or deleted")
        versions = result.get("Versions", [])
        require(isinstance(versions, list) and len(versions) <= 1 and
                all(item.get("Key") == key and item.get("IsLatest") is True and
                    isinstance(item.get("VersionId"), str) and
                    item["VersionId"] not in ("", "null") for item in versions),
                "Istio receipt history is ambiguous")
        return versions[0]["VersionId"] if versions else None

    def load(self, phase, status, required=True):
        return self.load_key(self.key(phase, status), required=required)

    def load_key(self, key, required=True):
        version = self.version(key)
        if version is None:
            require(not required, "Istio component receipt is missing")
            return None
        return json.loads(self.store.download(key, version, self.directory))

    def write(self, phase, status, record):
        key = self.key(phase, status)
        return self.write_key(key, record)

    def write_key(self, key, record):
        require(key == f"openclaw-enterprise/platform/stages/{STAGE}/verified.json" or
                any(key == self.key(number, state) for number in range(1, 7)
                    for state in ("started", "verified")) or
                any(key == self.attempt_key(number, record.get("runId"), state)
                    for number in range(1, 7) for state in ("started", "aborted")) or
                any(key == self.attestation_key(number, record.get("runId"))
                    for number in range(1, 7)),
                "unreviewed Istio receipt key")
        require(self.version(key) is None, "Istio component receipt already exists")
        path = self.directory / f"istio-{digest(key.encode())}.json"
        PLAT.save_inspection(path, record)
        content = path.read_bytes()
        checksum = base64.b64encode(hashlib.sha256(content).digest()).decode()
        response = self.store.call("s3api", "put-object", [
            "--key", key, "--body", str(path), "--if-none-match", "*",
            "--checksum-algorithm", "SHA256", "--checksum-sha256", checksum,
            "--server-side-encryption", "aws:kms", "--ssekms-key-id",
            f"arn:aws:kms:{self.store.target['region']}:{self.store.target['account_id']}:alias/aws/s3",
            "--bucket-key-enabled"])
        version = response.get("VersionId")
        require(isinstance(version, str) and version not in ("", "null") and
                response.get("ChecksumSHA256") == checksum and
                self.version(key) == version and
                self.store.download(key, version, self.directory) == content,
                "Istio component receipt writeback failed")
        return digest(content)

    def attempts(self, phase):
        prefix = ("openclaw-enterprise/platform/istio/1.28.10/components/"
                  f"phase-{phase}/attempts/")
        result = self.store.call("s3api", "list-object-versions",
                                 ["--prefix", prefix, "--no-paginate"])
        versions = result.get("Versions", [])
        require(result.get("IsTruncated") is False and not result.get("DeleteMarkers") and
                isinstance(versions, list) and len(versions) <= 64,
                "Istio attempt history is incomplete")
        records = {}
        for item in versions:
            key, version = item.get("Key"), item.get("VersionId")
            match = re.fullmatch(re.escape(prefix) + r"([1-9][0-9]*)/(started|aborted)\.json",
                                 key or "")
            require(match and key not in records and item.get("IsLatest") is True and
                    isinstance(version, str) and version not in ("", "null"),
                    "Istio attempt history is ambiguous")
            records[key] = json.loads(self.store.download(key, version, self.directory))
        return records

    def active_started(self, phase, required=True):
        root = self.load(phase, "started", required=required)
        if root is None:
            require(not self.attempts(phase), "Istio attempts exist without a start marker")
            return None
        validate_started_receipt(root, phase)
        rows = self.attempts(phase)
        candidates = [root]
        for key, row in rows.items():
            if key.endswith("/started.json"):
                validate_started_receipt(row, phase)
                require(row.get("rootStartedSha256") == digest(root) and
                        row["runId"] != root["runId"],
                        "Istio retry attempt does not bind the original start")
                candidates.append(row)
        active = []
        for row in candidates:
            aborted = rows.get(self.attempt_key(phase, row["runId"], "aborted"))
            if aborted is None:
                active.append(row)
            else:
                require(aborted.get("format") == 1 and aborted.get("stage") == STAGE and
                        aborted.get("phase") == phase and aborted.get("status") == "aborted" and
                        aborted.get("verified") is False and
                        aborted.get("runId") == row["runId"] and
                        aborted.get("startedSha256") == digest(row) and
                        aborted.get("previousConclusion") in ("failure", "cancelled", "timed_out") and
                        isinstance(aborted.get("sourceSha"), str) and
                        PLAT.SHA.fullmatch(aborted["sourceSha"]),
                        "Istio no-apply cancellation receipt is incomplete")
        require(len(active) <= 1, "multiple Istio apply attempts remain active")
        if required:
            require(len(active) == 1, "Istio phase has no active apply attempt")
        return active[0] if active else None


def admit_unstarted(store, phase):
    require(store.load(phase, "started", required=False) is None and
            store.load(phase, "verified", required=False) is None,
            "Istio phase already started; only protected verification or reviewed recovery is allowed")


def publish_or_reuse_verification(store, phase, started, record):
    """An interrupted post-write run may retry, but only under its same run ID."""
    existing = store.load(phase, "verified", required=False)
    if existing is None:
        store.write(phase, "verified", record)
        return record
    validate_verified_receipt(existing, started, phase)
    require(existing.get("sourceSha") == record.get("sourceSha") and
            existing.get("bundleSha256") == record.get("bundleSha256"),
            "Istio verified receipt belongs to a different source bundle")
    if (existing.get("runId") == record.get("runId") and
            existing.get("verificationSha") == record.get("verificationSha")):
        return existing
    attestation = {**record, "attestsSha256": digest(existing)}
    validate_attestation(attestation, existing, started, phase)
    key = store.attestation_key(phase, record["runId"])
    prior = store.load_key(key, required=False)
    if prior is None:
        store.write_key(key, attestation)
    else:
        validate_attestation(prior, existing, started, phase)
        require(prior["runId"] == record["runId"] and
                prior["verificationSha"] == record["verificationSha"],
                "Istio attestation run has different source")
        attestation = prior
    return attestation


def validate_attestation(attestation, original, started, phase):
    validate_verified_receipt(original, started, phase)
    validate_verified_receipt(attestation, started, phase)
    require(attestation.get("attestsSha256") == digest(original) and
            attestation.get("runId") != original.get("runId") and
            attestation.get("bundleSha256") == original.get("bundleSha256"),
            "Istio protected adoption does not bind the original receipt")
    return attestation


def publish_or_reuse_summary(store):
    components = {}
    for number in range(1, 7):
        started = store.active_started(number)
        verified = store.load(number, "verified")
        validate_verified_receipt(verified, started, number)
        components[str(number)] = digest(verified)
    require(components.get("6"), "final Istio component receipt is missing")
    last = store.load(6, "verified")
    final = {"format": 1, "stage": STAGE, "sourceSha": last["verificationSha"],
             "runId": last["runId"],
             "verified": True, "pinSha256": PLAT.PIN_SHA256,
             "observedVersion": "1.28.10", "components": components}
    key = f"openclaw-enterprise/platform/stages/{STAGE}/verified.json"
    existing = store.load_key(key, required=False)
    if existing is None:
        store.write_key(key, final)
    else:
        require(existing == final, "Istio stage summary belongs to a different source")


def validate_prior_receipt(store, candidate, phase, run):
    if phase == 1:
        stage = "talos-1.14.4"
        store.store.restore(stage, store.directory)
        path = store.directory / f"{stage}.json"
        require(path.exists(), "final Talos stage receipt is missing")
        PLAT.verify_stage_receipt(
            PLAT.validate_config(json.loads((ROOT / "scripts/config/platform-maintenance.json").read_text())),
            stage, PLAT.read_private_json(path), store.directory)
        require(PLAT.read_private_json(path).get("sourceSha") == run.get("head_sha"),
                "Talos receipt source differs from protected run")
        return
    previous = store.load(phase - 1, "verified")
    started = store.active_started(phase - 1)
    validate_verified_receipt(previous, started, phase - 1)
    if previous.get("runId") == candidate["priorRunId"]:
        require(previous.get("verificationSha") == run.get("head_sha"),
                "previous Istio phase differs from protected run")
        return
    attestation = store.load_key(store.attestation_key(phase - 1,
                                                       candidate["priorRunId"]))
    validate_attestation(attestation, previous, started, phase - 1)
    require(attestation.get("runId") == candidate["priorRunId"] and
            attestation.get("verificationSha") == run.get("head_sha"),
            "previous Istio phase lacks successful source-bound attestation")


def validate_started_receipt(started, phase):
    require(isinstance(started, dict) and started.get("format") == 1 and
            started.get("stage") == STAGE and started.get("phase") == phase and
            started.get("component") == GATE.COMPONENTS[phase - 1][1] and
            started.get("status") == "started" and started.get("verified") is False and
            isinstance(started.get("sourceSha"), str) and
            PLAT.SHA.fullmatch(started["sourceSha"]) and
            isinstance(started.get("runId"), str) and
            re.fullmatch(r"[1-9][0-9]*", started["runId"]) and
            all(isinstance(started.get(name), str) and re.fullmatch(r"[0-9a-f]{64}", started[name])
                for name in ("bundleSha256", "chartReceiptSha256",
                             "planSha256", "targetManifestSha256")) and
            isinstance(started.get("chartReceipt"), dict) and
            digest(started["chartReceipt"]) == started["chartReceiptSha256"] and
            isinstance(started.get("beforeApplication"), dict) and
            started["beforeApplication"].get("uid") and
            type(started["beforeApplication"].get("generation")) is int and
            isinstance(started.get("beforeWorkloads"), dict) and
            set(started["beforeWorkloads"]) == {name for _, name, _ in WORKLOADS} and
            isinstance(started.get("beforeCrds"), dict) and
            started["beforeCrds"].get("crdsSha256") and
            isinstance(started.get("beforePdb"), dict) and
            started["beforePdb"].get("uid") and
            started.get("beforeAdmission", {}).get("validationRejected") is True and
            started.get("beforeAdmission", {}).get("sidecarInjected") is True,
            "Istio start receipt is incomplete")
    return started


def validate_verified_receipt(record, started, phase):
    validate_started_receipt(started, phase)
    require(isinstance(record, dict) and record.get("format") == 1 and
            record.get("stage") == STAGE and record.get("phase") == phase and
            record.get("component") == GATE.COMPONENTS[phase - 1][1] and
            record.get("status") == "verified" and record.get("verified") is True and
            record.get("sourceSha") == started["sourceSha"] and
            record.get("applyRunId") == started["runId"] and
            record.get("startedSha256") == digest(started) and
            record.get("bundleSha256") == started["bundleSha256"] and
            record.get("chartReceiptSha256") == started["chartReceiptSha256"] and
            isinstance(record.get("verificationBundleSha256"), str) and
            re.fullmatch(r"[0-9a-f]{64}", record["verificationBundleSha256"]) and
            record["verificationBundleSha256"] ==
            source_bundle_at(record.get("verificationSha", "")) and
            isinstance(record.get("verificationSha"), str) and
            PLAT.SHA.fullmatch(record["verificationSha"]) and
            isinstance(record.get("runId"), str) and
            re.fullmatch(r"[1-9][0-9]*", record["runId"]) and
            record.get("xds", {}).get("acked") is True and
            record.get("hbone", {}).get("tls") is True and
            record["hbone"].get("database") == "ok" and
            isinstance(record.get("application"), dict) and
            record["application"].get("uid") == started["beforeApplication"]["uid"] and
            isinstance(record.get("workloads"), dict) and
            set(record["workloads"]) == {name for _, name, _ in WORKLOADS} and
            isinstance(record.get("crds"), dict) and
            len(record["crds"].get("webhooks", [])) == len(WEBHOOKS) and
            record.get("pdb") == started["beforePdb"] and
            record.get("admission", {}).get("validationRejected") is True and
            record.get("admission", {}).get("sidecarInjected") is True and
            isinstance(record.get("nodeSha256"), str) and
            re.fullmatch(r"[0-9a-f]{64}", record["nodeSha256"]),
            "Istio post-sync receipt is incomplete")
    PLAT.verify_path_probe(record.get("pathProbe"),
                           f"{STAGE}-phase-{phase}", "stage", record["verificationSha"])
    return record


def prerequisites(config, source_sha, store):
    store.store.load_prerequisites(source_sha, store.directory)
    records = {name: PLAT.read_private_json(store.directory / f"{name}.json")
               for name in PLAT.RECEIPTS}
    PLAT.verify_prerequisites(config, source_sha, records)
    PLAT.require_publication(config, source_sha, records["artifact-publication"])
    return records


def failed_apply_run(started, phase, current_sha):
    """Prove the previous serialized protected apply has stopped unsuccessfully."""
    run_id = started["runId"]
    run = json.loads(command("gh", "api", f"repos/{RUNS.REPOSITORY}/actions/runs/{run_id}"))
    title = f"Istio phase {phase} @ {started['sourceSha']}"
    require(run.get("id") == int(run_id) and run.get("head_sha") == started["sourceSha"] and
            run.get("head_branch") == "main" and run.get("event") == "workflow_dispatch" and
            run.get("path") == ".github/workflows/terragrunt-apply.yml" and
            run.get("name") == title and run.get("display_title") == title and
            run.get("status") == "completed" and
            run.get("conclusion") in ("failure", "cancelled", "timed_out") and
            subprocess.run(["git", "merge-base", "--is-ancestor", started["sourceSha"],
                            current_sha], cwd=ROOT, capture_output=True,
                           timeout=15).returncode == 0,
            "prior Istio apply is not a terminal failed ancestor")
    return run["conclusion"]


def successful_apply_run(started, phase, current_sha):
    run_id = started["runId"]
    run = json.loads(command("gh", "api", f"repos/{RUNS.REPOSITORY}/actions/runs/{run_id}"))
    title = f"Istio phase {phase} @ {started['sourceSha']}"
    require(run.get("id") == int(run_id) and run.get("head_sha") == started["sourceSha"] and
            run.get("head_branch") == "main" and run.get("event") == "workflow_dispatch" and
            run.get("path") == ".github/workflows/terragrunt-apply.yml" and
            run.get("name") == title and run.get("display_title") == title and
            run.get("status") == "completed" and run.get("conclusion") == "success" and
            subprocess.run(["git", "merge-base", "--is-ancestor", started["sourceSha"],
                            current_sha], cwd=ROOT, capture_output=True,
                           timeout=15).returncode == 0,
            "Istio source apply lacks a successful protected run")


def same_preapply_baseline(started, app, workloads, crds, pdb, admission,
                           target_hash, bundle_hash):
    before = started["beforeApplication"]
    require(started["targetManifestSha256"] == target_hash and
            started["bundleSha256"] == source_bundle_at(started["sourceSha"]) and
            bundle_hash == source_bundle() and
            all(app.get(field) == before.get(field)
                for field in ("uid", "generation", "sourcesSha256", "specSha256")) and
            workloads == started["beforeWorkloads"] and crds == started["beforeCrds"] and
            pdb == started["beforePdb"] and admission == started["beforeAdmission"],
            "prior Istio apply may have mutated the live baseline; reviewed recovery required")


def begin_or_resume_apply(store, phase, record, app, workloads, crds, pdb, admission):
    """Cancel only a terminal no-apply attempt, then append a fresh attempt."""
    root = store.load(phase, "started", required=False)
    if root is None:
        admit_unstarted(store, phase)
        store.write(phase, "started", record)
        return record
    validate_started_receipt(root, phase)
    require(store.load(phase, "verified", required=False) is None and
            root["runId"] != record["runId"],
            "Istio phase is already verified or the same apply run was restarted")
    active = store.active_started(phase, required=False)
    if active is not None:
        same_preapply_baseline(active, app, workloads, crds, pdb, admission,
                               record["targetManifestSha256"], record["bundleSha256"])
        conclusion = failed_apply_run(active, phase, record["sourceSha"])
        aborted = {"format": 1, "stage": STAGE, "phase": phase,
                   "status": "aborted", "verified": False,
                   "runId": active["runId"], "sourceSha": record["sourceSha"],
                   "startedSha256": digest(active), "previousConclusion": conclusion,
                   "applicationUid": app["uid"], "applicationGeneration": app["generation"],
                   "workloadsSha256": digest(workloads), "crdsSha256": digest(crds),
                   "pdbSha256": digest(pdb), "admissionSha256": digest(admission)}
        store.write_key(store.attempt_key(phase, active["runId"], "aborted"), aborted)
    else:
        same_preapply_baseline(root, app, workloads, crds, pdb, admission,
                               record["targetManifestSha256"], record["bundleSha256"])
    require(store.active_started(phase, required=False) is None,
            "prior Istio apply attempt remains active")
    require(store.load_key(store.attempt_key(phase, record["runId"], "started"),
                           required=False) is None,
            "Istio retry attempt already exists")
    record["rootStartedSha256"] = digest(root)
    store.write_key(store.attempt_key(phase, record["runId"], "started"), record)
    return record


def verify_nodes(config, talosconfig):
    observed = PLAT.read_only_inspection(config, talosconfig)
    require(PLAT.kubernetes_server_version() == "1.34.11" and
            all(node["talos"] == "1.14.4" and node["kubelet"] == "v1.34.11" and
                node["ready"] for node in observed["nodes"].values()),
            "Istio hop requires healthy Talos 1.14.4 and Kubernetes 1.34.11")
    PLAT.cluster_health(config, talosconfig)
    return digest(observed)


def preapply_nodes():
    nodes = PLAT._kubectl_json("get", "nodes").get("items")
    require(PLAT.kubernetes_server_version() == "1.34.11" and
            isinstance(nodes, list) and len(nodes) == len(PLAT.NODES) and
            {item.get("metadata", {}).get("name") for item in nodes} == set(PLAT.NODES) and
            all(item.get("status", {}).get("nodeInfo", {}).get("osImage") == "Talos (v1.14.4)" and
                item.get("status", {}).get("nodeInfo", {}).get("kubeletVersion") == "v1.34.11" and
                any(condition.get("type") == "Ready" and condition.get("status") == "True"
                    for condition in item.get("status", {}).get("conditions", []))
                for item in nodes),
            "Istio apply needs all four ready Talos 1.14.4 nodes on Kubernetes 1.34.11")


def normalized_live_spec(spec):
    value = copy.deepcopy(spec)
    require(value.pop("revisionHistoryLimit", None) == 10,
            "Istio Application history limit changed")
    require(value.get("destination", {}).get("name") is None,
            "Istio Application destination name changed")
    value["destination"]["name"] = ""
    retry = value["syncPolicy"]["retry"]
    for field, holder in (("limit", retry), ("factor", retry["backoff"])):
        require(type(holder[field]) is int, "Istio Application retry policy changed")
        holder[field] = str(holder[field])
    return value


def app_proof(phase, expected_spec, candidate):
    app = PLAT._kubectl_json("-n", "argocd", "get", "application", "istio")
    project = PLAT._kubectl_json("-n", "argocd", "get", "appproject", "homelab")
    require({f"{GATE.NEW_REPOSITORY}/{chart}" for chart, _, _ in GATE.COMPONENTS} <=
            set(project.get("spec", {}).get("sourceRepos", [])),
            "AppProject lacks reviewed Istio chart repository")
    metadata, spec, status = app["metadata"], app["spec"], app.get("status", {})
    require(metadata.get("uid") and not metadata.get("deletionTimestamp") and
            spec.get("project") == "homelab" and
            normalized_live_spec(spec) == expected_spec and
            status.get("sync", {}).get("status") == "Synced" and
            status.get("health", {}).get("status") == "Healthy" and
            status.get("operationState", {}).get("phase") in (None, "Succeeded"),
            "Istio Application is not healthy and synced")
    sources = spec.get("sources")
    revisions = status.get("sync", {}).get("revisions")
    require(isinstance(sources, list) and len(sources) == 8 and
            isinstance(revisions, list) and len(revisions) == 8,
            "Istio Application source or revision inventory changed")
    for index, (chart, release, _) in enumerate(GATE.COMPONENTS):
        expected = (f"{GATE.NEW_REPOSITORY}/{chart}",
                    candidate["chartManifestDigests"][chart]) if index < phase else (
                        GATE.OLD_REPOSITORY, "1.27.3")
        source = sources[index]
        require((source.get("repoURL"), source.get("targetRevision")) == expected and
                source.get("helm", {}).get("releaseName") == release and
                revisions[index] == expected[1],
                "Istio Application chart source is unsynced or out of order")
    require(all(source.get("targetRevision") == "main" for source in sources[6:]),
            "Istio Git-backed values no longer follow main")
    return {"uid": metadata["uid"], "generation": metadata.get("generation"),
            "revisionSha256": digest(revisions), "sourcesSha256": digest(sources),
            "specSha256": digest(normalized_live_spec(spec))}


def live_components(phase, config):
    """Check all five controllers and all selected Pods, including injected images."""
    listing = PLAT._kubectl_json("-n", "istio-system", "get", "deployments,daemonsets")
    pods = PLAT._kubectl_json("-n", "istio-system", "get", "pods")
    items = listing.get("items")
    pod_items = pods.get("items")
    require(isinstance(items, list) and isinstance(pod_items, list),
            "Istio workload inventory is incomplete")
    target = config["istioStages"][0]["images"]
    order = {"istiod": 2, "istio-cni-node": 3, "ztunnel": 4,
             "istio-ingressgateway": 5, "octelium-api-ingressgateway": 6}
    evidence = {}
    for kind, name, image_key in WORKLOADS:
        matches = [item for item in items if (item.get("kind"),
                   item.get("metadata", {}).get("name")) == (kind, name)]
        require(len(matches) == 1, "Istio workload identity is ambiguous")
        item = matches[0]
        metadata, spec, status = item["metadata"], item["spec"], item.get("status", {})
        desired = spec.get("replicas", 1) if kind == "Deployment" else len(PLAT.NODES)
        fields = ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas") if kind == "Deployment" else (
            "updatedNumberScheduled", "numberReady", "numberAvailable")
        require(metadata.get("uid") and not metadata.get("deletionTimestamp") and
                status.get("observedGeneration") == metadata.get("generation") and
                type(desired) is int and desired >= 1 and
                all(status.get(field) == desired for field in fields) and
                (kind != "DaemonSet" or
                 (status.get("desiredNumberScheduled") == len(PLAT.NODES) and
                  status.get("numberMisscheduled") == 0)),
                "Istio workload rollout is not fully observed")
        selector = spec.get("selector", {}).get("matchLabels")
        require(isinstance(selector, dict) and selector,
                "Istio workload selector is missing")
        selected = [pod for pod in pod_items if all(
            pod.get("metadata", {}).get("labels", {}).get(key) == value
            for key, value in selector.items())]
        require(len(selected) == desired, "Istio workload Pod count changed")
        updated = phase >= order[name]
        template = spec.get("template", {})
        template_containers = template.get("spec", {}).get("containers", [])
        require(len(template_containers) == 1,
                "Istio workload template container inventory changed")
        target_ref = digest_image(target[image_key])
        old_ref = f"docker.io/istio/{image_key}@sha256:{OLD_IMAGE_DIGESTS[image_key]}"
        old_tag = f"docker.io/istio/{image_key}:1.27.3-distroless"
        if image_key == "proxyv2":
            annotation = template.get("metadata", {}).get("annotations", {}).get(
                "sidecar.istio.io/proxyImage")
            require(template_containers[0].get("image") == "auto" and
                    (annotation == target_ref if updated else annotation is None),
                    "Istio gateway template injection digest changed")
        else:
            require(template_containers[0].get("image") == (
                target_ref if updated else old_tag),
                "Istio controller template image differs from reviewed source")
        for pod in selected:
            containers = pod.get("spec", {}).get("containers", [])
            statuses = pod.get("status", {}).get("containerStatuses", [])
            require(len(containers) == len(statuses) == 1 and
                    not pod.get("metadata", {}).get("deletionTimestamp") and
                    any(condition.get("type") == "Ready" and condition.get("status") == "True"
                        for condition in pod.get("status", {}).get("conditions", [])) and
                    statuses[0].get("ready") is True,
                    "Istio Pod is not ready")
            image = containers[0].get("image", "")
            image_id = statuses[0].get("imageID", "")
            if updated:
                require(image == target_ref and
                        image_id.endswith(target_ref.split("@sha256:")[1]),
                        "Istio Pod image differs from published target digest")
            else:
                require(image in (old_tag, old_ref) and
                        image_id.endswith(OLD_IMAGE_DIGESTS[image_key]),
                        "held Istio Pod image changed before its phase")
        evidence[name] = {"uid": metadata["uid"], "generation": metadata["generation"],
                          "podsSha256": digest(sorted(pod["metadata"]["uid"] for pod in selected)),
                          "target": updated}
    return evidence, pod_items


def crd_and_webhook_proof():
    crds = PLAT._kubectl_json("get", "crds").get("items", [])
    found = {item.get("metadata", {}).get("name"): item for item in crds}
    require(all(name in found and any(
        condition.get("type") == "Established" and condition.get("status") == "True"
        for condition in found[name].get("status", {}).get("conditions", []))
        for name in CRDS), "Istio CRDs are not Established")
    service = PLAT._kubectl_json("-n", "istio-system", "get", "service", "istiod")
    slices = PLAT._kubectl_json("-n", "istio-system", "get", "endpointslices", "-l",
                               "kubernetes.io/service-name=istiod").get("items", [])
    require(service.get("metadata", {}).get("uid") and any(
        endpoint.get("conditions", {}).get("ready") is True
        for item in slices for endpoint in item.get("endpoints", [])),
        "Istiod webhook Service has no ready endpoint")
    expected_hooks = {
        "istio-validator-istio-system": {"rev.validation.istio.io"},
        "istiod-default-validator": {"validation.istio.io"},
        "istio-sidecar-injector": {
            "rev.namespace.sidecar-injector.istio.io",
            "rev.object.sidecar-injector.istio.io",
            "namespace.sidecar-injector.istio.io",
            "object.sidecar-injector.istio.io",
        },
    }
    def valid_ca_bundle(value):
        if not isinstance(value, str):
            return False
        try:
            return len(base64.b64decode(value, validate=True)) >= 512
        except (ValueError, binascii.Error):
            return False

    for kind, name in WEBHOOKS:
        item = PLAT._kubectl_json("get", kind, name)
        webhooks = item.get("webhooks", [])
        path = "/inject" if kind == "mutatingwebhookconfiguration" else "/validate"
        require(item.get("metadata", {}).get("uid") and
                {hook.get("name") for hook in webhooks} == expected_hooks[name] and all(
            hook.get("failurePolicy") == "Fail" and
            hook.get("clientConfig", {}).get("service") == {
                "name": "istiod", "namespace": "istio-system", "path": path, "port": 443} and
            valid_ca_bundle(hook.get("clientConfig", {}).get("caBundle"))
            for hook in webhooks), "Istio admission webhook TLS or failure policy changed")
    return {"crdsSha256": digest({name: found[name]["metadata"]["uid"] for name in CRDS}),
            "serviceUid": service["metadata"]["uid"],
            "webhooks": [name for _, name in WEBHOOKS]}


def admission_proof(phase, config):
    """Server dry-run proves both semantic rejection and actual sidecar mutation."""
    invalid = {"apiVersion": "networking.istio.io/v1", "kind": "VirtualService",
               "metadata": {"name": "istio-validation-probe", "namespace": "default"},
               "spec": {"hosts": ["istio-validation-probe.example.invalid"],
                        "http": [{"match": [{"uri": {"regex": "["}}],
                                  "route": [{"destination": {
                                      "host": "kubernetes.default.svc.cluster.local"}}]}]}}
    command_line = ["kubectl", "--request-timeout=15s", "create", "--dry-run=server",
                    "-f", "-", "-o", "json"]
    rejected = subprocess.run(command_line, input=json.dumps(invalid), capture_output=True,
                              text=True, timeout=30, check=False)
    require(rejected.returncode != 0 and
            'admission webhook "validation.istio.io" denied the request' in rejected.stderr and
            "error parsing regexp" in rejected.stderr,
            "Istio validating webhook did not reject invalid routing")
    pod = {"apiVersion": "v1", "kind": "Pod",
           "metadata": {"name": "istio-injection-probe", "namespace": "istio-system",
                        "labels": {"sidecar.istio.io/inject": "true"}},
           "spec": {"automountServiceAccountToken": False,
                    "containers": [{"name": "probe", "image": "registry.k8s.io/pause:3.9"}]}}
    mutated = subprocess.run(command_line, input=json.dumps(pod), capture_output=True,
                             text=True, timeout=30, check=False)
    require(mutated.returncode == 0, "Istio mutating admission dry-run failed")
    value = json.loads(mutated.stdout)
    status = json.loads(value.get("metadata", {}).get("annotations", {}).get(
        "sidecar.istio.io/status", "null"))
    init = value.get("spec", {}).get("initContainers", [])
    proxies = [item for item in init if item.get("name") == "istio-proxy"]
    expected = ("docker.io/istio/proxyv2:1.27.3-distroless" if phase < 2 else
                OLD_PROXY_IMAGE if phase < 6 else
                digest_image(config["istioStages"][0]["images"]["proxyv2"]))
    require(value.get("metadata", {}).get("name") == pod["metadata"]["name"] and
            value.get("metadata", {}).get("namespace") == "istio-system" and
            isinstance(status, dict) and status.get("revision") == "default" and
            len(proxies) == 1 and proxies[0].get("image") == expected and
            {item.get("name") for item in init} >= {"istio-init", "istio-proxy"},
            "Istio mutating webhook did not inject the reviewed sidecar image")
    return {"validationRejected": True, "sidecarInjected": True,
            "sidecarImage": expected}


def pdb_proof():
    item = PLAT._kubectl_json("-n", "istio-system", "get", "pdb", "istiod")
    metadata, spec = item.get("metadata", {}), item.get("spec", {})
    require(metadata.get("uid") and not metadata.get("deletionTimestamp") and
            spec.get("minAvailable") == 1 and spec.get("maxUnavailable") is None and
            isinstance(spec.get("selector", {}).get("matchLabels"), dict) and
            spec["selector"]["matchLabels"].get("app") == "istiod",
            "held Istiod PodDisruptionBudget was pruned or changed")
    return {"uid": metadata["uid"], "specSha256": digest(spec)}


def port_forward(namespace, resource, remote_port):
    process = subprocess.Popen(["kubectl", "-n", namespace, "port-forward", "--address",
                                "127.0.0.1", resource, f":{remote_port}"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1)
    deadline = time.monotonic() + 20
    try:
        while time.monotonic() < deadline and process.poll() is None:
            ready, _, _ = select.select([process.stdout], [], [], 1)
            if ready:
                line = process.stdout.readline().strip()
                match = re.fullmatch(rf"Forwarding from 127\.0\.0\.1:(\d+) -> {remote_port}", line)
                if match:
                    return process, int(match.group(1))
        raise ValueError("Istio port-forward was not ready")
    except BaseException:
        process.terminate()
        process.wait(timeout=5)
        raise


def stop_forward(process):
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    if process.stdout:
        process.stdout.close()


def xds_proof(pods, phase):
    istiod = [pod for pod in pods if pod.get("metadata", {}).get("labels", {}).get("app") == "istiod"]
    require(len(istiod) == 1, "Istiod debug endpoint identity changed")
    process, port = port_forward("istio-system", f"pod/{istiod[0]['metadata']['name']}", 8080)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/debug/syncz", timeout=10) as response:
            payload = response.read(1048577)
        require(len(payload) <= 1048576, "Istio xDS response is unbounded")
    finally:
        stop_forward(process)
    proxies = json.loads(payload)
    require(isinstance(proxies, list), "Istio xDS response is invalid")
    expected = {f"{pod['metadata']['name']}.istio-system" for pod in pods
                if pod.get("metadata", {}).get("labels", {}).get("app") in
                ("ztunnel", "istio-ingressgateway", "octelium-api-ingressgateway")}
    actual = {item.get("proxy") for item in proxies}
    ztunnel = {name for name in expected if name.startswith("ztunnel-")}
    def expected_version(proxy):
        if proxy.startswith("ztunnel-"):
            return "1.28.10" if phase >= 4 else "1.27.3"
        if proxy.startswith("istio-ingressgateway-"):
            return "1.28.10" if phase >= 5 else "1.27.3"
        return "1.28.10" if phase >= 6 else "1.27.3"
    require(ztunnel <= actual and actual == expected and len(proxies) == len(actual) and
            any(name.startswith("istio-ingressgateway-") for name in actual) and
            any(name.startswith("octelium-api-ingressgateway-") for name in actual) and all(
        item.get("istio_version") == expected_version(item.get("proxy", "")) and
        isinstance(item.get("resources"), dict) and item["resources"] and
        all(resource.get("sent") == resource.get("acked") and resource.get("acked")
            for resource in item["resources"].values())
        for item in proxies), "Istio xDS has missing proxies or unacknowledged resources")
    return {"proxyIds": sorted(actual), "proxyIdsSha256": digest(sorted(actual)),
            "acked": True}


def hbone_proof(pods, xds):
    namespace = PLAT._kubectl_json("get", "namespace", "monitoring")
    grafana = PLAT._kubectl_json("-n", "monitoring", "get", "pods", "-l",
                                 "app.kubernetes.io/name=grafana,app.kubernetes.io/instance=grafana")
    require(namespace.get("metadata", {}).get("labels", {}).get("istio.io/dataplane-mode") == "ambient" and
            len(grafana.get("items", [])) == 1 and
            grafana["items"][0].get("metadata", {}).get("annotations", {}).get(
                "ambient.istio.io/redirection") == "enabled",
            "Grafana ambient destination is not redirected")
    gateway = [pod for pod in pods if pod.get("metadata", {}).get("labels", {}).get("app") ==
               "istio-ingressgateway" and
               f"{pod['metadata']['name']}.istio-system" in xds["proxyIds"]]
    require(gateway, "reviewed Istio ingress gateway Pod is missing")
    chosen = sorted(gateway, key=lambda pod: pod["metadata"]["name"])[0]
    process, port = port_forward("istio-system", f"pod/{chosen['metadata']['name']}", 443)
    try:
        # A local TLS connection preserves the real Host/SNI and certificate
        # verification while traversing the gateway's ambient Grafana route.
        import http.client
        class LocalHTTPS(http.client.HTTPSConnection):
            def connect(self):
                raw = self._create_connection(("127.0.0.1", port), self.timeout)
                self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        connection = LocalHTTPS("grafana.stinkyboi.com", timeout=10,
                                context=ssl.create_default_context())
        try:
            connection.request("GET", "/api/health")
            response = connection.getresponse()
            body = response.read(4097)
            require(response.status == 200 and len(body) <= 4096 and
                    json.loads(body).get("database") == "ok",
                    "Istio gateway to ambient Grafana path failed")
        finally:
            connection.close()
    finally:
        stop_forward(process)
    return {"gateway": chosen["metadata"]["uid"],
            "grafana": grafana["items"][0]["metadata"]["uid"],
            "database": "ok", "tls": True}


def preapply(args):
    candidate, config, phase = protected_source(args.expected_sha)
    require(args.phase == phase and os.environ.get("GITHUB_RUN_ID", "").isdigit(),
            "Istio apply phase and protected run disagree")
    require(args.plan_dir.is_dir() and args.rendered.is_file(),
            "saved Istio plan or render is missing")
    rendered = json.loads(args.rendered.read_text())
    GATE.check_sources(rendered, candidate)
    GATE.check_referenced_content(ROOT, phase)
    GATE.authorize_plan(args.plan_dir, rendered, candidate, allow_transition=True)
    with tempfile.TemporaryDirectory(prefix="istio-preapply-") as directory:
        path = Path(directory)
        path.chmod(0o700)
        store = Receipts(path)
        prerequisites(config, args.expected_sha, store)
        previous_start = store.load(phase, "started", required=False)
        if previous_start is None:
            run = public_runs(candidate, args.expected_sha)
            chart_receipt = chart_publication_receipt(candidate)
        else:
            validate_started_receipt(previous_start, phase)
            original_candidate = candidate_at(previous_start["sourceSha"])
            require(all(candidate[key] == original_candidate[key] for key in (
                "phase", "priorRunId", "harborRunId", "chartRunId",
                "chartManifestDigests")),
                "Istio retry changed protected publication identity")
            run = public_runs(original_candidate, previous_start["sourceSha"])
            chart_receipt = saved_chart_publication_receipt(previous_start, candidate)
        validate_prior_receipt(store, candidate, phase, run)
        preapply_nodes()
        plan = next(args.plan_dir.glob("**/istio/argocd/tfplan.json"))
        before = json.loads(plan.read_text())["resource_changes"][0]["change"]["before"]
        app = app_proof(phase - 1, before["manifest"]["spec"], candidate)
        workloads, _ = live_components(phase - 1, config)
        crds = crd_and_webhook_proof()
        pdb = pdb_proof()
        admission = admission_proof(phase - 1, config)
        # Talos/Kubernetes versions are checked in the post-sync lane with
        # authenticated Talos mTLS, before a completion receipt can exist.
        record = {"format": 1, "stage": STAGE, "phase": phase,
                  "component": GATE.COMPONENTS[phase - 1][1],
                  "sourceSha": args.expected_sha, "runId": os.environ["GITHUB_RUN_ID"],
                  "status": "started", "verified": False,
                  "bundleSha256": source_bundle(),
                  "chartReceipt": chart_receipt,
                  "chartReceiptSha256": digest(chart_receipt),
                  "beforeApplication": app,
                  "beforeWorkloads": workloads, "beforeCrds": crds,
                  "beforePdb": pdb,
                  "beforeAdmission": admission,
                  "planSha256": digest(plan.read_bytes()),
                  "targetManifestSha256": digest(rendered["inputs"]["manifest"])}
        require(PLAT.current_main_sha() == args.expected_sha,
                "main advanced before Istio start marker")
        begin_or_resume_apply(store, phase, record, app, workloads, crds, pdb, admission)
        require(PLAT.current_main_sha() == args.expected_sha,
                "main advanced after Istio start marker")
    print("Istio protected start marker verified; one saved Application plan may apply")


def verify(args):
    candidate, config, phase = protected_source(args.expected_sha)
    require(args.phase == phase and os.environ.get("GITHUB_RUN_ID", "").isdigit(),
            "Istio verification phase and protected run disagree")
    store = Receipts(args.receipt_dir)
    prerequisites(config, args.expected_sha, store)
    started = store.active_started(phase)
    validate_started_receipt(started, phase)
    original_candidate = candidate_at(started["sourceSha"])
    require(original_candidate["phase"] == phase and
            original_candidate["chartManifestDigests"] == candidate["chartManifestDigests"],
            "Istio source phase or immutable chart targets changed after apply")
    public_runs(original_candidate, started["sourceSha"])
    saved_chart_publication_receipt(started, candidate)
    successful_apply_run(started, phase, args.expected_sha)
    require(started.get("bundleSha256") == source_bundle_at(started["sourceSha"]) and
            subprocess.run(["git", "merge-base", "--is-ancestor", started["sourceSha"],
                            args.expected_sha], cwd=ROOT, timeout=15).returncode == 0,
            "Istio start marker is absent, changed, or already verified")
    # Verification can resume after interruption. It never reapplies the plan.
    node_hash = verify_nodes(config, args.talosconfig)
    rendered = json.loads(command("terragrunt", "--log-disable", "--working-dir",
                                  "IaC/homelab/us-west-2/apps/istio/argocd",
                                  "render", "--json", "--write=false", "--no-color",
                                  timeout=90))
    GATE.check_sources(rendered, candidate)
    GATE.check_referenced_content(ROOT, phase)
    require(digest(rendered["inputs"]["manifest"]) == started["targetManifestSha256"],
            "reviewed Istio target manifest changed after apply")
    app = app_proof(phase, rendered["inputs"]["manifest"]["spec"], candidate)
    require(app["uid"] == started["beforeApplication"]["uid"] and
            app["generation"] > started["beforeApplication"]["generation"],
            "Istio Application did not advance the reviewed source")
    workloads, pods = live_components(phase, config)
    crds = crd_and_webhook_proof()
    pdb = pdb_proof()
    admission = admission_proof(phase, config)
    require(pdb == started["beforePdb"], "Istiod PDB was removed during staged sync")
    path = PLAT.inter_node_path_probe(config, args.talosconfig,
                                      f"{STAGE}-phase-{phase}", "stage", args.expected_sha)
    xds = xds_proof(pods, phase)
    hbone = hbone_proof(pods, xds)
    require(PLAT.current_main_sha() == args.expected_sha,
            "main advanced before Istio verification receipt")
    record = {"format": 1, "stage": STAGE, "phase": phase,
              "component": GATE.COMPONENTS[phase - 1][1],
              "sourceSha": started["sourceSha"], "verificationSha": args.expected_sha,
              "applyRunId": started["runId"],
              "runId": os.environ["GITHUB_RUN_ID"], "status": "verified", "verified": True,
              "startedSha256": digest(started),
              "bundleSha256": started["bundleSha256"],
              "verificationBundleSha256": source_bundle(),
              "chartReceiptSha256": started["chartReceiptSha256"],
              "nodeSha256": node_hash, "application": app, "workloads": workloads,
              "crds": crds, "admission": admission,
              "pathProbe": path, "xds": xds, "hbone": hbone}
    record["pdb"] = pdb
    validate_verified_receipt(record, started, phase)
    record = publish_or_reuse_verification(store, phase, started, record)
    if phase == 6:
        publish_or_reuse_summary(store)
    PLAT.save_inspection(args.receipt_dir / f"{STAGE}-phase-{phase}.json", record)
    print(f"Istio phase {phase} post-sync verification and private receipt complete")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    pre = sub.add_parser("preapply")
    pre.add_argument("--phase", type=int, required=True)
    pre.add_argument("--expected-sha", required=True)
    pre.add_argument("--plan-dir", type=Path, required=True)
    pre.add_argument("--rendered", type=Path, required=True)
    post = sub.add_parser("verify")
    post.add_argument("--phase", type=int, required=True)
    post.add_argument("--expected-sha", required=True)
    post.add_argument("--talosconfig", type=Path, required=True)
    post.add_argument("--receipt-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "preapply":
        preapply(args)
    else:
        verify(args)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, AttributeError,
            json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"Istio protected operation held: {error}", file=sys.stderr)
        sys.exit(1)
