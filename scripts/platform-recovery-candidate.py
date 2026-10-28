#!/usr/bin/env python3
"""Capture and stage non-authoritative Talos recovery candidates on the LAN Mac.

Capture reads Talos and exact offsite S3 versions, then restores a downloaded
copy offline. Stage writes only those private candidate JSON bytes to the
dedicated etcd bucket for separate protected review. Neither mode publishes
authoritative platform-maintenance receipts or client credentials.
"""

import argparse
import base64
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}\Z")
LAN = ipaddress.ip_network("10.1.0.0/24")
PORT = 50000
PROXY_ENV = {"http_proxy", "https_proxy", "all_proxy", "no_proxy",
             "talosconfig", "talos_endpoint", "talos_node"}
SCOPE = "operator-local-candidate"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


OFFSITE = module("platform_candidate_offsite", "etcd-offsite-backup.py")
RESTORE = module("platform_candidate_restore", "etcd-offline-restore-check.py")
PLATFORM = module("platform_candidate_maintenance", "platform-maintenance.py")


class ReadOnlyAWS(OFFSITE.AWS):
    """Limit this command even when the existing SSO profile is an administrator."""

    ALLOWED = {("sts", "get-caller-identity"),
               ("s3api", "get-bucket-versioning"),
               ("s3api", "get-object")}

    def call(self, service, operation, arguments=(), missing=False):
        if (service, operation) not in self.ALLOWED or missing:
            raise ValueError("recovery candidate may only read the offsite bucket")
        return super().call(service, operation, arguments)


class StagingAWS(OFFSITE.AWS):
    """Only stage non-authoritative JSON in the dedicated etcd bucket."""

    ALLOWED = {("sts", "get-caller-identity"),
               ("s3api", "get-bucket-versioning"),
               ("s3api", "get-bucket-encryption"),
               ("s3api", "put-object"), ("s3api", "head-object"),
               ("s3api", "get-object"), ("s3api", "list-object-versions")}

    def call(self, service, operation, arguments=(), missing=False):
        if (service, operation) not in self.ALLOWED or missing:
            raise ValueError("candidate staging requested an unreviewed AWS operation")
        return super().call(service, operation, arguments)


def quiet(command, *, cwd=ROOT, env=None, timeout=30):
    """Never forward raw CLI diagnostics; Talos output can contain secrets."""
    result = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=timeout, check=False)
    if result.returncode or len(result.stdout) > 128 * 1024:
        raise ValueError("required local verification failed")
    return result.stdout.decode("utf-8")


def require_main(expected):
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise ValueError("invalid reviewed main revision")
    selectors = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                 "GIT_CONFIG_COUNT", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
                 "GH_HOST"}
    if any(name in os.environ for name in selectors):
        raise ValueError("ambient source or GitHub selector is forbidden")
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_") and key != "GH_HOST"}
    if quiet(["git", "rev-parse", "--show-toplevel"], env=env).strip() != str(ROOT):
        raise ValueError("source checkout differs from this producer")
    origin = quiet(["git", "remote", "get-url", "origin"], env=env).strip()
    if origin not in ("https://github.com/Stuhlmuller/homelab.git",
                      "git@github.com:Stuhlmuller/homelab.git"):
        raise ValueError("source remote differs from reviewed repository")
    if quiet(["git", "rev-parse", "HEAD"], env=env).strip() != expected:
        raise ValueError("producer is not the reviewed main revision")
    if quiet(["git", "status", "--porcelain"], env=env).strip():
        raise ValueError("producer checkout is not clean")
    current = quiet(["gh", "api", "--hostname", "github.com",
                     "repos/Stuhlmuller/homelab/git/ref/heads/main",
                     "--jq", ".object.sha"], env=env).strip()
    if current != expected:
        raise ValueError("main advanced during recovery capture")


def private_file(path):
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("private client config must be an absolute regular file")
    path = path.resolve(strict=True)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
            stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
        raise ValueError("private client config must be owned and mode 0600")
    return path


def private_fingerprint(path):
    """Pin the existing private client file without displaying its contents."""
    path = private_file(path)
    before = path.lstat()
    def identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                info.st_ctime_ns, info.st_mode, info.st_uid, info.st_nlink)
    if not 0 < before.st_size <= 1024 * 1024:
        raise ValueError("private client config has an invalid size")
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("private client config changed")
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("private client config changed")
    if identity(path.lstat()) != identity(before):
        raise ValueError("private client config changed")
    return digest.hexdigest()


def executable(path):
    if not path.is_absolute():
        raise ValueError("Talos client must be an absolute executable")
    path = path.resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("Talos client must be an absolute executable")
    return path


def direct_environment():
    # A local proxy or ambient Talos selector must not change the intended path.
    return {key: value for key, value in os.environ.items()
            if key.lower() not in PROXY_ENV}


@contextlib.contextmanager
def talos_environment():
    previous = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(direct_environment_from(previous))
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def direct_environment_from(source):
    return {key: value for key, value in source.items()
            if key.lower() not in PROXY_ENV}


def direct_route(address, *, run=quiet, connect=None):
    """Require a macOS en-interface and same-subnet TCP source."""
    if sys.platform != "darwin" or ipaddress.ip_address(address) not in LAN:
        raise ValueError("direct recovery requires the operator LAN Mac")
    route = run(["/sbin/route", "-n", "get", address])
    matches = re.findall(r"^\s*interface:\s*(en[0-9]+)\s*$", route, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError("Talos route is not a macOS en interface")
    if connect is None:
        def connect():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
                stream.settimeout(5)
                stream.connect((address, PORT))
                return stream.getsockname()[0]
    source = ipaddress.ip_address(connect())
    if source not in LAN or source == ipaddress.ip_address(address):
        raise ValueError("Talos TCP source is not the operator LAN")
    return matches[0], str(source)


def captured_utc_seconds(value):
    """Convert the backup manifest's exact UTC ISO timestamp to gate format."""
    if (not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?\+00:00", value)):
        raise ValueError("snapshot capture timestamp is invalid")
    captured = datetime.fromisoformat(value)
    result = captured.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    PLATFORM.fresh_recovery_time(result)
    return result


def direct_talos(config, talosconfig, talosctl, *, run=quiet, route=direct_route):
    expected = config["expectedStart"]["talos"]
    env = direct_environment()
    client = run([str(talosctl), "--talosconfig", str(talosconfig),
                  "version", "--client", "--short"], env=env).strip()
    if client != f"Client:\nTalos v{expected}":
        raise ValueError("Talos client differs from the reviewed cluster version")
    nodes = config["expectedStart"]["nodes"]
    if set(nodes) != {"acer", "zimaboard-0", "zimaboard-1", "zimaboard-2"}:
        raise ValueError("reviewed Talos node set changed")
    interfaces = set()
    sources = set()
    for name in ("zimaboard-0", "zimaboard-1", "zimaboard-2", "acer"):
        address = nodes[name]["address"]
        before = route(address)
        output = run([str(talosctl), "--talosconfig", str(talosconfig),
                      "--endpoints", address, "--nodes", address,
                      "version", "--short"], env=env, timeout=30)
        server = output.split("Server:", 1)
        if (len(server) != 2 or output.count("Server:") != 1 or
                not re.search(rf"(?m)^[ \t]*Talos v{re.escape(expected)}[ \t]*$",
                              server[1])):
            raise ValueError("authenticated Talos node version is unavailable")
        after = route(address)
        if before != after:
            raise ValueError("Talos direct LAN route changed during authentication")
        interfaces.add(before[0])
        sources.add(before[1])
    if len(interfaces) != 1 or len(sources) != 1:
        raise ValueError("Talos nodes do not share one direct LAN route")
    control = nodes["acer"]["address"]
    before = route(control)
    if before != (next(iter(interfaces)), next(iter(sources))):
        raise ValueError("direct-LAN etcd route differs from node probes")
    status = run([str(talosctl), "--talosconfig", str(talosconfig),
                  "--endpoints", control, "--nodes", control,
                  "etcd", "status"], env=env, timeout=30)
    if not status.strip() or route(control) != before:
        raise ValueError("direct-LAN etcd status is unavailable")
    workers = ",".join(nodes[name]["address"] for name in
                       ("zimaboard-0", "zimaboard-1", "zimaboard-2"))
    if route(control) != before:
        raise ValueError("direct-LAN health route changed before check")
    run([str(talosctl), "--talosconfig", str(talosconfig),
         "--endpoints", control, "health", "--control-plane-nodes", control,
         "--worker-nodes", workers, "--wait-timeout", "30s"],
        env=env, timeout=45)
    if route(control) != before:
        raise ValueError("direct-LAN health route changed")
    return {"interface": interfaces.pop(), "sourceAddress": sources.pop(),
            "nodeAddresses": {name: nodes[name]["address"] for name in nodes},
            "nodeEndpoints": {name: f"{nodes[name]['address']}:{PORT}"
                              for name in nodes},
            "controlPlaneEndpoint": f"{control}:{PORT}",
            "etcdStatusRead": True, "directClusterHealth": True}


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode()


def write_candidate(directory, name, value):
    path = directory / f"{name}.candidate.json"
    content = canonical(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    OFFSITE.backup.sync_directory(directory)
    return hashlib.sha256(content).hexdigest()


def candidate_files(directory, source_sha):
    """Revalidate private candidate bytes; staging cannot promote their claims."""
    directory = OFFSITE.backup.private_directory(directory)
    app_target = OFFSITE.read_inputs(ROOT / "IaC/application-backup-storage.hcl")
    if (set(app_target) != {"account_id", "region", "bucket"} or
            not re.fullmatch(r"[0-9]{12}", app_target["account_id"]) or
            app_target["region"] != "us-east-1" or
            app_target["bucket"] !=
            f"homelab-application-backups-{app_target['account_id']}-us-east-1"):
        raise ValueError("unreviewed platform candidate destination")
    expected_bucket = app_target["bucket"]
    result = {}
    for name in ("direct-recovery", "off-node-etcd-backup"):
        path = directory / f"{name}.candidate.json"
        OFFSITE.private_file(path)
        if path.lstat().st_nlink != 1:
            raise ValueError("private candidate has an unexpected hard link")
        digest = OFFSITE.digest(path)
        if digest["bytes"] > 1024 * 1024:
            raise ValueError("recovery candidate exceeds the private JSON limit")
        raw = path.read_bytes()
        value = json.loads(raw)
        if (not isinstance(value, dict) or raw != canonical(value) or
                value.get("format") != 1 or
                value.get("scope") != SCOPE or value.get("verified") is not False or
                value.get("sourceSha") != source_sha or
                value.get("targetBucket") != expected_bucket or
                value.get("targetKey") !=
                f"openclaw-enterprise/platform/receipts/{source_sha}/{name}.json"):
            raise ValueError("private candidate differs from the reviewed source contract")
        PLATFORM.fresh_recovery_time(value.get("capturedAt"))
        result[name] = (path, digest, value)
    direct = result["direct-recovery"][2]
    config = json.loads((ROOT / "scripts/config/platform-maintenance.json").read_text())
    nodes = config["expectedStart"]["nodes"]
    expected_names = ["zimaboard-0", "zimaboard-1", "zimaboard-2", "acer"]
    if (direct.get("nodes") != expected_names or
            direct.get("endpoint") != "10.1.0.199:50000" or
            direct.get("controlPlaneEndpoint") != direct["endpoint"] or
            direct.get("nodeAddresses") != {name: nodes[name]["address"] for name in nodes} or
            direct.get("nodeEndpoints") !=
            {name: f"{nodes[name]['address']}:{PORT}" for name in nodes} or
            direct.get("transport") != "direct-lan-authenticated-talos" or
            direct.get("talosMtls") is not True or
            direct.get("etcdStatusRead") is not True or
            direct.get("directClusterHealth") is not True or
            not re.fullmatch(r"en[0-9]+", str(direct.get("interface"))) or
            ipaddress.ip_address(direct.get("sourceAddress")) not in LAN or
            not re.fullmatch(r"[0-9a-f]{64}", str(direct.get("talosconfigSha256")))):
        raise ValueError("private direct-LAN candidate is incomplete")
    backup = result["off-node-etcd-backup"][2]
    offsite = OFFSITE.destination()
    snapshot_sha = backup.get("snapshotSha256")
    prefix = f"etcd/{snapshot_sha}/"
    if (backup.get("offNode") is not True or
            backup.get("offlineRestoreVerified") is not True or
            not isinstance(snapshot_sha, str) or
            not re.fullmatch(r"[0-9a-f]{64}", snapshot_sha) or
            backup.get("offsiteBucket") != offsite["bucket"] or
            not isinstance(backup.get("snapshotKey"), str) or
            not re.fullmatch(re.escape(prefix) + r"[0-9a-f]{32}/etcd\.snapshot",
                             backup["snapshotKey"]) or
            backup.get("manifestKey") !=
            backup["snapshotKey"].removesuffix("etcd.snapshot") + "manifest.json" or
            any(not isinstance(backup.get(key), str) or
                backup[key] in ("", "null") or len(backup[key]) > 1024 or
                any(ord(char) < 32 or ord(char) > 126 for char in backup[key])
                for key in ("objectVersionId", "manifestVersionId")) or
            any(not re.fullmatch(r"[0-9a-f]{64}", str(backup.get(key)))
                for key in ("manifestSha256", "restoreReceiptSha256")) or
            any(type(backup.get(key)) is not int or backup[key] <= 0
                for key in ("snapshotBytes", "manifestBytes"))):
        raise ValueError("private off-node candidate is incomplete")
    restore_path = directory / "offline-restore.receipt.json"
    OFFSITE.private_file(restore_path)
    if restore_path.lstat().st_nlink != 1:
        raise ValueError("offline restore receipt has an unexpected hard link")
    restore_digest = OFFSITE.digest(restore_path)
    if restore_digest["bytes"] > 1024 * 1024:
        raise ValueError("offline restore receipt exceeds the private JSON limit")
    restore = json.loads(restore_path.read_bytes())
    if not isinstance(restore, dict):
        raise ValueError("offline restore receipt is not a JSON object")
    integrity = restore.get("source_integrity")
    if (restore_digest["sha256"] != backup["restoreReceiptSha256"] or
            restore.get("format") != 1 or
            restore.get("validation") != "offline-database-restore" or
            restore.get("source_unchanged") is not True or
            restore.get("restore_checksum_enabled") is not True or
            restore.get("server_started") is not False or
            restore.get("control_plane_recovery_tested") is not False or
            not isinstance(integrity, dict) or
            integrity.get("sha256") != backup["snapshotSha256"] or
            integrity.get("bytes") != backup["snapshotBytes"] or
            not isinstance(restore.get("tool"), dict) or
            restore["tool"].get("version") != RESTORE.VERSION):
        raise ValueError("offline restore receipt is not bound to the candidate")
    result["offline-restore"] = (restore_path, restore_digest, restore)
    return result


def stage(args):
    """Stage immutable candidate bytes for separate protected review only."""
    source_sha = args.expected_sha
    require_main(source_sha)
    directory = OFFSITE.backup.private_directory(args.candidate_directory)
    if (directory / "staging.json").exists() or (directory / "staging.json").is_symlink():
        raise ValueError("candidate staging already has a local result")
    files = candidate_files(directory, source_sha)
    aws = StagingAWS(args.aws_cli, args.profile, OFFSITE.destination())
    aws.check()
    encryption = aws.call("s3api", "get-bucket-encryption")
    expected_key = (f"arn:aws:kms:{aws.target['region']}:"
                    f"{aws.target['account_id']}:alias/aws/s3")
    rules = encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules")
    if (not isinstance(rules, list) or len(rules) != 1 or
            not isinstance(rules[0], dict) or
            rules[0].get("ApplyServerSideEncryptionByDefault") !=
            {"SSEAlgorithm": "aws:kms", "KMSMasterKeyID": expected_key} or
            rules[0].get("BucketKeyEnabled") is not True):
        raise ValueError("offsite staging bucket encryption differs")
    prefix = f"platform-candidates/{source_sha}/{uuid.uuid4().hex}"
    staged = {}
    for name in ("direct-recovery", "off-node-etcd-backup", "offline-restore"):
        require_main(source_sha)
        path, digest, _ = files[name]
        if OFFSITE.digest(path) != digest:
            raise ValueError("private candidate changed before staging")
        filename = ("offline-restore.receipt.json" if name == "offline-restore"
                    else f"{name}.candidate.json")
        key = f"{prefix}/{filename}"
        checksum = base64.b64encode(bytes.fromhex(digest["sha256"])).decode()
        response = aws.call("s3api", "put-object", [
            "--key", key, "--body", str(path), "--if-none-match", "*",
            "--checksum-algorithm", "SHA256", "--checksum-sha256", checksum,
            "--server-side-encryption", "aws:kms", "--ssekms-key-id", expected_key,
            "--bucket-key-enabled"])
        version = response.get("VersionId")
        if (not isinstance(version, str) or version in ("", "null") or
                response.get("ChecksumSHA256") != checksum):
            raise ValueError("candidate S3 upload lacks an immutable version")
        head = aws.call("s3api", "head-object", ["--key", key, "--version-id", version,
                                               "--checksum-mode", "ENABLED"])
        OFFSITE.object_metadata(head, digest, version)
        kms_key = re.compile(rf"arn:aws:kms:{aws.target['region']}:"
                             rf"{aws.target['account_id']}:key/[A-Za-z0-9-]+\Z")
        if not isinstance(head.get("SSEKMSKeyId"), str) or not kms_key.fullmatch(
                head["SSEKMSKeyId"]):
            raise ValueError("candidate S3 version uses an unreviewed KMS key")
        history = aws.call("s3api", "list-object-versions", [
            "--prefix", key, "--no-paginate"])
        versions = history.get("Versions")
        if (history.get("IsTruncated") is not False or history.get("DeleteMarkers") or
                not isinstance(versions, list) or len(versions) != 1 or
                not isinstance(versions[0], dict) or
                {field: versions[0].get(field) for field in
                 ("Key", "VersionId", "IsLatest")} !=
                {"Key": key, "VersionId": version, "IsLatest": True}):
            raise ValueError("candidate S3 version history is ambiguous")
        with tempfile.TemporaryDirectory(prefix="staging-readback-", dir=directory) as scratch:
            target = Path(scratch) / "candidate.json"
            metadata = aws.call("s3api", "get-object", [
                "--key", key, "--version-id", version, "--checksum-mode", "ENABLED",
                str(target)])
            target.chmod(0o600)
            OFFSITE.object_metadata(metadata, digest, version)
            if metadata.get("SSEKMSKeyId") != head["SSEKMSKeyId"]:
                raise ValueError("candidate S3 version KMS key changed on readback")
            if OFFSITE.digest(target) != digest or OFFSITE.digest(path) != digest:
                raise ValueError("candidate S3 version differs from private reviewed bytes")
        staged[name] = {"key": key, "versionId": version, **digest}
    require_main(source_sha)
    receipt = {"format": 1, "scope": "operator-candidate-staging", "verified": False,
               "sourceSha": source_sha, "bucket": aws.target["bucket"],
               "prefix": prefix, "objects": staged}
    content = canonical(receipt)
    fd = os.open(directory / "staging.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    OFFSITE.backup.sync_directory(directory)
    return receipt


def capture(args):
    """Produce two private candidates; neither satisfies the upgrade gate."""
    source_sha = args.expected_sha
    require_main(source_sha)
    config = json.loads((ROOT / "scripts/config/platform-maintenance.json").read_text())
    PLATFORM.validate_config(config)
    talosconfig = private_file(args.talosconfig)
    talosconfig_sha = private_fingerprint(talosconfig)
    talosctl = executable(args.talosctl)
    receipt_root = OFFSITE.backup.private_directory(args.receipt_directory)
    retrieval_root = OFFSITE.backup.private_directory(args.retrieval_directory)
    restore_root = OFFSITE.backup.private_directory(args.restore_directory)
    publication = OFFSITE.backup.private_directory(args.publication_directory)
    paths = (receipt_root, retrieval_root, restore_root, publication)
    if any(left == right or left in right.parents or right in left.parents
           for index, left in enumerate(paths) for right in paths[index + 1:]):
        raise ValueError("private recovery directories must be disjoint")
    with talos_environment():
        direct = direct_talos(config, talosconfig, talosctl)
    aws = ReadOnlyAWS(args.aws_cli, args.profile, OFFSITE.destination())
    _, publication_record = OFFSITE.load(publication, aws.target, require_files=False)
    if publication_record.get("status") != "verified":
        raise ValueError("offsite publication is not independently verified")
    retrieved = OFFSITE.retrieve(publication, retrieval_root, aws)
    snapshot = OFFSITE.backup.verify(retrieved)
    if (snapshot.get("format") != 1 or snapshot.get("snapshot") != "etcd.snapshot" or
            snapshot.get("source_node") != "10.1.0.199"):
        raise ValueError("downloaded etcd manifest has an unreviewed source")
    snapshot_time = captured_utc_seconds(snapshot.get("created_at"))
    restored, restore_record = RESTORE.restore_check(retrieved, restore_root,
                                                     args.etcd_archive)
    if (restore_record.get("validation") != "offline-database-restore" or
            restore_record.get("source_integrity") != snapshot["integrity"] or
            restore_record.get("restore_checksum_enabled") is not True or
            restore_record.get("source_unchanged") is not True or
            restore_record.get("server_started") is not False or
            restore_record.get("control_plane_recovery_tested") is not False or
            not isinstance(restore_record.get("tool"), dict) or
            restore_record["tool"].get("version") != RESTORE.VERSION or
            OFFSITE.backup.verify(retrieved) != snapshot):
        raise ValueError("downloaded etcd copy did not pass offline restore")
    OFFSITE.private_file(restored / "receipt.json")
    _, publication_record_after = OFFSITE.load(publication, aws.target,
                                               require_files=False)
    if publication_record_after != publication_record:
        raise ValueError("offsite publication changed during offline restore")
    with talos_environment():
        if direct_talos(config, talosconfig, talosctl) != direct:
            raise ValueError("operator LAN route changed during recovery capture")
    if private_fingerprint(talosconfig) != talosconfig_sha:
        raise ValueError("Talos client config changed during recovery capture")
    direct_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    PLATFORM.fresh_recovery_time(direct_time)
    PLATFORM.fresh_recovery_time(snapshot_time)
    require_main(source_sha)
    app_target = OFFSITE.read_inputs(ROOT / "IaC/application-backup-storage.hcl")
    if (set(app_target) != {"account_id", "region", "bucket"} or
            not re.fullmatch(r"[0-9]{12}", app_target["account_id"]) or
            app_target["region"] != "us-east-1" or
            app_target["bucket"] !=
            f"homelab-application-backups-{app_target['account_id']}-us-east-1"):
        raise ValueError("unreviewed platform receipt destination")
    prefix = f"openclaw-enterprise/platform/receipts/{source_sha}"
    names = ["zimaboard-0", "zimaboard-1", "zimaboard-2", "acer"]
    common = {"format": 1, "scope": SCOPE, "sourceSha": source_sha,
              "verified": False}
    direct_record = {**common, "capturedAt": direct_time,
                     "transport": "direct-lan-authenticated-talos",
                     "endpoint": "10.1.0.199:50000", "nodes": names,
                     "talosMtls": True, "talosconfigSha256": talosconfig_sha, **direct,
                     "targetBucket": app_target["bucket"],
                     "targetKey": f"{prefix}/direct-recovery.json"}
    objects = publication_record["objects"]
    backup_record = {**common, "capturedAt": snapshot_time,
                     "offNode": True, "offlineRestoreVerified": True,
                     "snapshotSha256": snapshot["integrity"]["sha256"],
                     "objectVersionId": objects["etcd.snapshot"]["version_id"],
                     "offsiteBucket": aws.target["bucket"],
                     "snapshotKey": f"{publication_record['prefix']}/etcd.snapshot",
                     "manifestKey": f"{publication_record['prefix']}/manifest.json",
                     "manifestVersionId": objects["manifest.json"]["version_id"],
                     "manifestSha256": objects["manifest.json"]["digest"]["sha256"],
                     "manifestBytes": objects["manifest.json"]["digest"]["bytes"],
                     "snapshotBytes": objects["etcd.snapshot"]["digest"]["bytes"],
                     "restoreReceiptSha256": hashlib.sha256(
                         (restored / "receipt.json").read_bytes()).hexdigest(),
                     "targetBucket": app_target["bucket"],
                     "targetKey": f"{prefix}/off-node-etcd-backup.json"}
    if (not all(isinstance(objects[name]["version_id"], str) and
                objects[name]["version_id"] not in ("", "null")
                for name in OFFSITE.FILES) or
            backup_record["snapshotSha256"] !=
            objects["etcd.snapshot"]["digest"]["sha256"]):
        raise ValueError("offsite object versions do not match the restored snapshot")
    candidate_dir = Path(tempfile.mkdtemp(prefix="platform-candidate-", dir=receipt_root))
    restore_copy = candidate_dir / "offline-restore.receipt.json"
    restore_bytes = (restored / "receipt.json").read_bytes()
    if not 0 < len(restore_bytes) <= 1024 * 1024:
        raise ValueError("offline restore receipt has an invalid size")
    fd = os.open(restore_copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(restore_bytes)
        output.flush()
        os.fsync(output.fileno())
    if OFFSITE.digest(restore_copy)["sha256"] != backup_record["restoreReceiptSha256"]:
        raise ValueError("offline restore receipt changed while copying")
    write_candidate(candidate_dir, "direct-recovery", direct_record)
    write_candidate(candidate_dir, "off-node-etcd-backup", backup_record)
    OFFSITE.backup.sync_directory(receipt_root)
    return candidate_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture_command = commands.add_parser("capture")
    capture_command.add_argument("--expected-sha", required=True)
    capture_command.add_argument("--talosconfig", required=True, type=Path)
    capture_command.add_argument("--talosctl", required=True, type=Path)
    capture_command.add_argument("--aws-cli", required=True, type=Path)
    capture_command.add_argument("--profile", default="default")
    capture_command.add_argument("--publication-directory", required=True, type=Path)
    capture_command.add_argument("--retrieval-directory", required=True, type=Path)
    capture_command.add_argument("--restore-directory", required=True, type=Path)
    capture_command.add_argument("--etcd-archive", required=True, type=Path)
    capture_command.add_argument("--receipt-directory", required=True, type=Path)
    stage_command = commands.add_parser("stage")
    stage_command.add_argument("--expected-sha", required=True)
    stage_command.add_argument("--candidate-directory", required=True, type=Path)
    stage_command.add_argument("--aws-cli", required=True, type=Path)
    stage_command.add_argument("--profile", default="default")
    args = parser.parse_args()
    previous = os.umask(0o077)
    try:
        if args.command == "capture":
            capture(args)
            print("Private non-authoritative recovery candidates saved.")
        else:
            stage(args)
            print("Non-authoritative recovery candidate versions staged.")
        return 0
    except (OSError, ValueError, TypeError, KeyError, UnicodeError,
            subprocess.SubprocessError, socket.error):
        print("Recovery candidate capture failed; retain existing snapshots and "
              "partial private copies. Talos, AWS, and database diagnostics withheld.",
              file=sys.stderr)
        return 1
    finally:
        os.umask(previous)


if __name__ == "__main__":
    sys.exit(main())
