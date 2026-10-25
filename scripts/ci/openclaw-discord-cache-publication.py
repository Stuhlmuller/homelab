#!/usr/bin/env python3
"""Publish or transfer the pinned public Discord npm cache through private S3.

Only the protected, exact-main OpenClaw operations workflow may call this helper.
The cache is public package content; neither legacy state nor credentials enter it.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "scripts/openclaw-discord-offline-cache.py"
DOWNLOAD = ROOT / "scripts/ci/openclaw-enterprise-download.py"
PREFIX = "openclaw-enterprise/legacy-discord-cache"
NAMES = ("npm-cache.tar", "dependency-lock.json", "manifest.json")
SHA = re.compile(r"[0-9a-f]{40}\Z")
RUN = re.compile(r"[1-9][0-9]*\Z")
BUCKET = re.compile(r"homelab-application-backups-[0-9]{12}-us-east-1\Z")
READER_MIRROR = "harbor.stinkyboi.com/mirror/"
READER_SOURCE_VOLUMES = {
    "local": ("openclaw-runtime-local", "/runtime-volume"),
    "state": ("openclaw-runtime-state-local", "/legacy-state"),
    "agent": ("openclaw-runtime-agent-local", "/legacy-agent"),
    "nas": ("openclaw", "/data"),
}
READER_ARCHIVE = ("openclaw-retirement-archive", "/archive")
READER_CONFIG_MAPS = {"scripts": "openclaw-assistant", "retirement-scripts": "openclaw-retirement"}
READER_MOUNTS = {
    *((name, path, True) for name, (_, path) in READER_SOURCE_VOLUMES.items()),
    ("archive", "/archive", False),
    ("private", "/private", False),
    ("private", "/tmp", False),
    ("scripts", "/etc/openclaw-assistant", True),
    ("retirement-scripts", "/etc/openclaw-retirement", True),
}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    with path.open("rb") as content:
        return hashlib.file_digest(content, "sha256").hexdigest()


def valid_version(version):
    # S3 version IDs are opaque. Keep them as argv elements, never shell text.
    return (isinstance(version, str) and 0 < len(version) <= 1024 and
            version not in ("None", "null") and all(33 <= ord(char) <= 126 for char in version))


def call(command, *, data=None):
    result = subprocess.run(command, input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=600, check=False)
    if result.returncode:
        raise ValueError("protected cache operation failed")
    return result.stdout


def aws(*args):
    raw = call(["aws", "s3api", *args, "--output", "json"])
    return json.loads(raw)


def check_bucket(bucket):
    source = (ROOT / "IaC/application-backup-storage.hcl").read_text()
    configured = re.findall(r'^\s*bucket\s*=\s*"([a-z0-9-]+)"\s*$', source, re.M)
    if not BUCKET.fullmatch(bucket) or configured != [bucket]:
        raise ValueError("unreviewed cache bucket")
    if aws("get-bucket-versioning", "--bucket", bucket).get("Status") != "Enabled":
        raise ValueError("cache bucket versioning changed")
    rules = aws("get-bucket-encryption", "--bucket", bucket)[
        "ServerSideEncryptionConfiguration"]["Rules"]
    if rules[0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] != "aws:kms":
        raise ValueError("cache bucket encryption changed")


def object_key(source_sha, run_id, name):
    if not SHA.fullmatch(source_sha) or not RUN.fullmatch(run_id) or name not in (*NAMES, "final.json"):
        raise ValueError("invalid cache source reference")
    return f"{PREFIX}/{source_sha}/{run_id}/{name}"


def exact_versions(bucket, key):
    response = aws("list-object-versions", "--no-paginate", "--bucket", bucket,
                   "--prefix", key)
    if response.get("IsTruncated") is not False:
        raise ValueError("cache version listing truncated")
    return ([item for item in response.get("Versions", []) if item["Key"] == key],
            [item for item in response.get("DeleteMarkers", []) if item["Key"] == key])


def head_exact(bucket, key, version, size):
    if not valid_version(version):
        raise ValueError("invalid cache object version")
    head = aws("head-object", "--bucket", bucket, "--key", key,
               "--version-id", version)
    if (head.get("VersionId") != version or head.get("ContentLength") != size or
            head.get("ServerSideEncryption") != "aws:kms"):
        raise ValueError("cache object metadata changed")


def read_exact(bucket, key, version, path, size, sha):
    head_exact(bucket, key, version, size)
    response = aws("get-object", "--bucket", bucket, "--key", key,
                   "--version-id", version, str(path))
    if (response.get("VersionId") != version or response.get("ContentLength") != size or
            path.stat().st_size != size or digest(path) != sha):
        raise ValueError("cache object differs from receipt")


def publish(bucket, source_sha, run_id, directory):
    builder = load(BUILDER, "openclaw_discord_cache_builder")
    builder.verify_bundle(directory, ROOT)
    check_bucket(bucket)
    keys = {name: object_key(source_sha, run_id, name) for name in (*NAMES, "final.json")}
    for key in keys.values():
        if any(exact_versions(bucket, key)):
            raise ValueError("cache publication prefix already used")
    files = {}
    with tempfile.TemporaryDirectory(prefix="openclaw-cache-publish-") as scratch:
        scratch = Path(scratch)
        for name in NAMES:
            path = directory / name
            response = aws("put-object", "--bucket", bucket, "--key", keys[name],
                           "--body", str(path), "--if-none-match", "*")
            version = response.get("VersionId", "")
            size = path.stat().st_size
            sha = digest(path)
            if not valid_version(version):
                raise ValueError("cache publication lacks immutable version")
            read_exact(bucket, keys[name], version, scratch / name, size, sha)
            files[name] = {"versionId": version, "size": size, "sha256": sha}
        final = {"format": 1, "sourceSha": source_sha, "runId": run_id,
                 "files": files}
        final_path = scratch / "final.json"
        final_path.write_text(json.dumps(final, sort_keys=True, separators=(",", ":")) + "\n")
        final_path.chmod(0o600)
        response = aws("put-object", "--bucket", bucket, "--key", keys["final.json"],
                       "--body", str(final_path), "--if-none-match", "*")
        version = response.get("VersionId", "")
        if not valid_version(version):
            raise ValueError("cache final receipt lacks immutable version")
        read_exact(bucket, keys["final.json"], version, scratch / "final-check.json",
                   final_path.stat().st_size, digest(final_path))
    return f"{source_sha}/{run_id}"


def validate_final(final, source_sha, run_id, builder):
    if (set(final) != {"format", "sourceSha", "runId", "files"} or
            final["format"] != 1 or final["sourceSha"] != source_sha or
            final["runId"] != run_id or set(final["files"]) != set(NAMES)):
        raise ValueError("cache final receipt identity changed")
    for name in NAMES:
        entry = final["files"][name]
        if (set(entry) != {"versionId", "size", "sha256"} or
                not valid_version(entry["versionId"]) or
                type(entry["size"]) is not int or not 0 < entry["size"] <= builder.MAX_BYTES[name] or
                not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
            raise ValueError("cache final receipt file contract changed")


def secure_reader_container(container):
    security = container.get("securityContext", {})
    return (security.get("runAsUser", 1000) == 1000 and
            security.get("runAsNonRoot") is not False and
            security.get("allowPrivilegeEscalation") is False and
            security.get("readOnlyRootFilesystem") is True and
            security.get("privileged") is not True and
            security.get("seccompProfile", {}).get("type", "RuntimeDefault") == "RuntimeDefault" and
            security.get("capabilities", {}).get("drop") == ["ALL"] and
            not security.get("capabilities", {}).get("add"))


def mount_contract(mounts):
    if any("subPath" in mount or "subPathExpr" in mount for mount in mounts):
        return None
    return {(mount.get("name"), mount.get("mountPath"), mount.get("readOnly", False))
            for mount in mounts}


def reader_context(pod, uid, builder):
    if not re.fullmatch(r"openclaw-retirement-reader-[a-z0-9-]+", pod) or not re.fullmatch(
        r"[0-9a-f-]{36}", uid
    ):
        raise ValueError("invalid retirement reader identity")
    info = json.loads(call(["kubectl", "-n", "ai", "get", "pod", pod, "-o", "json"]))
    spec = info["spec"]
    readers = [container for container in spec["containers"] if container["name"] == "reader"]
    init = spec.get("initContainers", [])
    pod_security = spec.get("securityContext", {})
    if (info["metadata"]["uid"] != uid or info["status"]["phase"] != "Running" or
            pod_security.get("runAsUser") != 1000 or
            pod_security.get("runAsNonRoot") is not True or
            pod_security.get("seccompProfile", {}).get("type") != "RuntimeDefault" or
            spec.get("automountServiceAccountToken") is not False or
            any(spec.get(flag) is True for flag in ("hostNetwork", "hostPID", "hostIPC")) or
            len(spec["containers"]) != 1 or len(readers) != 1 or
            spec.get("ephemeralContainers") or
            readers[0]["image"] != READER_MIRROR + builder.IMAGE or
            not secure_reader_container(readers[0]) or len(init) != 1 or
            init[0].get("name") != "private-archive-directory" or
            init[0].get("image") != READER_MIRROR + builder.IMAGE or
            init[0].get("command") != ["/bin/sh", "-ec"] or
            init[0].get("args") != [
                "test ! -L /archive/private && mkdir -p /archive/private && chmod 700 /archive/private"] or
            not secure_reader_container(init[0]) or
            mount_contract(init[0].get("volumeMounts", [])) != {("archive", "/archive", False)} or
            len(init[0].get("volumeMounts", [])) != 1):
        raise ValueError("retirement reader identity changed")
    volumes = spec.get("volumes", [])
    mounts = readers[0].get("volumeMounts", [])
    volume_names = [volume.get("name") for volume in volumes]
    expected_names = set(READER_SOURCE_VOLUMES) | {"archive", "private"} | set(READER_CONFIG_MAPS)
    if (len(volume_names) != len(expected_names) or set(volume_names) != expected_names or
            len(mounts) != len(READER_MOUNTS) or mount_contract(mounts) != READER_MOUNTS):
        raise ValueError("retirement reader storage changed")
    volume_by_name = {volume["name"]: volume for volume in volumes}
    for name, (claim, _) in READER_SOURCE_VOLUMES.items():
        volume = volume_by_name[name]
        if (set(volume) != {"name", "persistentVolumeClaim"} or
                volume["persistentVolumeClaim"] != {"claimName": claim, "readOnly": True}):
            raise ValueError("retirement reader storage changed")
    archive = volume_by_name["archive"]
    if (set(archive) != {"name", "persistentVolumeClaim"} or
            archive["persistentVolumeClaim"].get("claimName") != READER_ARCHIVE[0] or
            archive["persistentVolumeClaim"].get("readOnly") is True or
            set(volume_by_name["private"]) != {"name", "emptyDir"} or
            volume_by_name["private"]["emptyDir"] != {}):
        raise ValueError("retirement reader storage changed")
    for name, config_map in READER_CONFIG_MAPS.items():
        volume = volume_by_name[name]
        if (set(volume) != {"name", "configMap"} or
                volume["configMap"].get("name") != config_map):
            raise ValueError("retirement reader storage changed")


REMOTE_PREPARE = r'''import os, stat, sys
base = '/archive/private'
run = sys.argv[1]
for path in ('/archive', base):
    item = os.lstat(path)
    if not stat.S_ISDIR(item.st_mode):
        raise ValueError('archive scratch parent changed')
fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    os.mkdir('discord-cache-' + run, 0o700, dir_fd=fd)
    child = os.stat('discord-cache-' + run, dir_fd=fd, follow_symlinks=False)
    if not stat.S_ISDIR(child.st_mode) or stat.S_IMODE(child.st_mode) != 0o700:
        raise ValueError('archive scratch mode changed')
finally:
    os.close(fd)
'''


REMOTE_COMPLETE = r'''import hashlib, json, os, stat, sys
directory = sys.argv[1]
receipt = json.loads(sys.stdin.buffer.read(65536))
if os.path.realpath(directory) != directory or not stat.S_ISDIR(os.lstat(directory).st_mode):
    raise ValueError('cache scratch path changed')
if stat.S_IMODE(os.stat(directory).st_mode) != 0o700:
    raise ValueError('cache scratch mode changed')
if set(os.listdir(directory)) != set(receipt['files']):
    raise ValueError('cache scratch file set changed')
for name, expected in receipt['files'].items():
    path = directory + '/' + name
    item = os.lstat(path)
    if not stat.S_ISREG(item.st_mode) or stat.S_IMODE(item.st_mode) != 0o600 or item.st_size != expected['size']:
        raise ValueError('cache scratch file identity changed')
    with open(path, 'rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != expected['sha256']:
            raise ValueError('cache scratch digest changed')
marker = directory + '/completed.json'
fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
try:
    with os.fdopen(fd, 'wb') as output:
        output.write(json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode() + b'\n')
        output.flush()
        os.fsync(output.fileno())
except BaseException:
    os.unlink(marker)
    raise
'''


def transfer(bucket, cache_ref, pod, pod_uid, transfer_sha, transfer_run):
    source_sha, run_id = cache_ref.split("/", 1)
    builder = load(BUILDER, "openclaw_discord_cache_builder")
    download = load(DOWNLOAD, "openclaw_discord_cache_download")
    check_bucket(bucket)
    final_key = object_key(source_sha, run_id, "final.json")
    versions, markers = exact_versions(bucket, final_key)
    if len(versions) != 1 or markers:
        raise ValueError("cache final receipt version is ambiguous")
    version = versions[0]["VersionId"]
    if not valid_version(version) or not 0 < versions[0]["Size"] <= 65536:
        raise ValueError("cache final receipt size changed")
    with tempfile.TemporaryDirectory(prefix="openclaw-cache-transfer-") as scratch:
        directory = Path(scratch)
        final_path = directory / "final.json"
        response = aws("get-object", "--bucket", bucket, "--key", final_key,
                       "--version-id", version, str(final_path))
        if response.get("VersionId") != version or final_path.stat().st_size != versions[0]["Size"]:
            raise ValueError("cache final receipt bytes changed")
        head_exact(bucket, final_key, version, final_path.stat().st_size)
        final = json.loads(final_path.read_text())
        validate_final(final, source_sha, run_id, builder)
        for name in NAMES:
            entry = final["files"][name]
            read_exact(bucket, object_key(source_sha, run_id, name), entry["versionId"],
                       directory / name, entry["size"], entry["sha256"])
        final_path.unlink()
        builder.verify_bundle(directory, ROOT)
        reader_context(pod, pod_uid, builder)
        destination = f"/archive/private/discord-cache-{transfer_run}"
        call(["kubectl", "-n", "ai", "exec", pod, "-c", "reader", "--",
              "python3", "-c", REMOTE_PREPARE, transfer_run])
        for name in NAMES:
            entry = final["files"][name]
            download.restore_version(bucket, object_key(source_sha, run_id, name),
                                     entry["versionId"], destination + "/" + name,
                                     entry["size"], entry["sha256"], pod)
        reader_context(pod, pod_uid, builder)
        completed = {"format": 1, "cacheRef": cache_ref, "transferSha": transfer_sha,
                     "transferRunId": transfer_run, "files": final["files"]}
        call(["kubectl", "-n", "ai", "exec", "-i", pod, "-c", "reader", "--",
              "python3", "-c", REMOTE_COMPLETE, destination],
             data=json.dumps(completed, sort_keys=True).encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("publish", "transfer"))
    parser.add_argument("bucket")
    parser.add_argument("source")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--reader-pod")
    parser.add_argument("--reader-uid")
    args = parser.parse_args()
    source_sha = os.environ.get("GITHUB_SHA", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if (os.environ.get("GITHUB_ACTIONS") != "true" or
            not SHA.fullmatch(source_sha) or not RUN.fullmatch(run_id)):
        parser.error("protected source identity required")
    if args.operation == "publish":
        if args.source != f"{source_sha}/{run_id}" or args.directory is None or args.reader_pod:
            parser.error("publication source changed")
        publish(args.bucket, source_sha, run_id, args.directory)
    else:
        if (not re.fullmatch(r"[0-9a-f]{40}/[1-9][0-9]*", args.source) or
                args.directory is not None or not args.reader_pod or not args.reader_uid):
            parser.error("transfer source changed")
        transfer(args.bucket, args.source, args.reader_pod, args.reader_uid,
                 source_sha, run_id)
    print("Private Discord cache operation completed; receipt contents withheld")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
            subprocess.TimeoutExpired):
        print("Private Discord cache operation failed; diagnostics withheld", file=sys.stderr)
        raise SystemExit(1) from None
