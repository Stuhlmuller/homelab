#!/usr/bin/env python3
"""Stream one namespace-local recovery archive over a private exec channel.

This source-only helper never authorizes a writer stop or publishes an archive.
The future protected coordinator must supply authenticated Pod/PVC observations,
capture stdout privately, require exit zero, and keep a continuous writer fence.
Do not run it as a Pod command: that would place recovery bytes in Pod logs.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import tarfile


SHA = re.compile(r"[0-9a-f]{40}\Z")
UID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
DNS = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z")
GATEWAY_CLAIM = re.compile(r"gateway-state-[0-9a-f]{12}\Z")
MAX_INPUT_BYTES = 1024 * 1024
MAX_ARCHIVE_BYTES = 16 * 1024 ** 3
MAX_ARCHIVE_FILES = 100_000
CHUNK = 1024 * 1024
ROOTS = {
    "operator": {"journal": Path("/source/journal"),
                 "bootstrap": Path("/source/bootstrap")},
    "tenant": {"state": Path("/source/gateway")},
}
NAMESPACES = {"operator": "openclaw-system", "tenant": "openclaw-agents"}
CLAIM_NAMES = {"journal": "occ-operator-journal",
               "bootstrap": "occ-bootstrap-admin-password"}
CLASSES = {"journal": "openclaw-enterprise-journal-local",
           "bootstrap": "openclaw-enterprise-bootstrap-local",
           "gateway": "openclaw-enterprise-agent-local"}


class Blocked(RuntimeError):
    pass


def require(value):
    if not value:
        raise Blocked


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def read_observation(stream):
    data = stream.read(MAX_INPUT_BYTES + 1)
    require(isinstance(data, bytes) and len(data) <= MAX_INPUT_BYTES)
    return json.loads(data)


def validate_observation(kind, source_sha, pod_uid, expected_uids, observation):
    require(kind in ROOTS and SHA.fullmatch(source_sha) and UID.fullmatch(pod_uid))
    namespace = NAMESPACES[kind]
    keys = {"schemaVersion", "sourceSha", "readerPod", "claims"}
    if kind == "tenant":
        keys.add("tenantPods")
    require(isinstance(observation, dict) and set(observation) == keys and
            observation["schemaVersion"] == 1 and
            observation["sourceSha"] == source_sha)
    pod = observation["readerPod"]
    metadata = pod.get("metadata") if isinstance(pod, dict) else None
    spec = pod.get("spec") if isinstance(pod, dict) else None
    require(isinstance(metadata, dict) and isinstance(spec, dict) and
            metadata.get("namespace") == namespace and
            metadata.get("uid") == pod_uid and
            metadata.get("deletionTimestamp") is None and
            isinstance(metadata.get("name"), str) and
            DNS.fullmatch(metadata["name"]) and
            spec.get("automountServiceAccountToken") is False and
            spec.get("hostNetwork") is False and
            spec.get("hostPID") in (None, False) and
            spec.get("hostIPC") in (None, False) and
            spec.get("restartPolicy") == "Never" and
            spec.get("initContainers") in (None, []) and
            spec.get("ephemeralContainers") in (None, []) and
            spec.get("securityContext") == {
                "runAsUser": 1000, "runAsNonRoot": True,
                "seccompProfile": {"type": "RuntimeDefault"}})
    containers = spec.get("containers")
    require(isinstance(containers, list) and len(containers) == 1 and
            isinstance(containers[0], dict) and
            containers[0].get("securityContext") == {
                "allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": True,
                "capabilities": {"drop": ["ALL"]}})
    claims = observation["claims"]
    required = {"journal", "bootstrap"} if kind == "operator" else {"gateway"}
    require(isinstance(claims, dict) and set(claims) == required and
            isinstance(expected_uids, dict) and set(expected_uids) == required and
            all(isinstance(uid, str) and UID.fullmatch(uid)
                for uid in expected_uids.values()))
    names = {}
    for key in required:
        claim = claims[key]
        cm = claim.get("metadata") if isinstance(claim, dict) else None
        cs = claim.get("spec") if isinstance(claim, dict) else None
        require(isinstance(cm, dict) and isinstance(cs, dict) and
                cm.get("namespace") == namespace and
                cm.get("uid") == expected_uids[key] and
                isinstance(cm.get("resourceVersion"), str) and
                cm["resourceVersion"] and
                cm.get("deletionTimestamp") is None and
                isinstance(cm.get("name"), str) and
                (cm["name"] == CLAIM_NAMES[key] if key in CLAIM_NAMES else
                 GATEWAY_CLAIM.fullmatch(cm["name"])) and
                cs.get("storageClassName") == CLASSES[key] and
                cs.get("accessModes") == ["ReadWriteOnce"] and
                isinstance(cs.get("volumeName"), str) and cs["volumeName"] and
                isinstance(claim.get("status"), dict) and
                claim["status"].get("phase") == "Bound")
        names[key] = cm["name"]
    volumes = spec.get("volumes")
    mounts = containers[0].get("volumeMounts")
    require(isinstance(volumes, list) and isinstance(mounts, list) and
            len(volumes) == len(required) and len(mounts) == len(required))
    volume_map = {item.get("name"): item.get("persistentVolumeClaim")
                  for item in volumes if isinstance(item, dict)}
    mount_map = {item.get("name"): item for item in mounts
                 if isinstance(item, dict)}
    require(set(volume_map) == required and set(mount_map) == required and
            all(volume_map[key] == {"claimName": names[key], "readOnly": True}
                and mount_map[key] == {"name": key,
                                       "mountPath": "/source/" + key,
                                       "readOnly": True} for key in required))
    if kind == "tenant":
        listing = observation["tenantPods"]
        lm = listing.get("metadata") if isinstance(listing, dict) else None
        require(isinstance(lm, dict) and listing.get("kind") == "PodList" and
                isinstance(lm.get("resourceVersion"), str) and
                lm["resourceVersion"] and lm.get("continue") in (None, "") and
                listing.get("items") == [pod])
    return namespace


def fingerprint(info):
    return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode),
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def safe_name(name):
    require(isinstance(name, str) and name not in ("", ".", "..") and
            "/" not in name and "\\" not in name and
            not any(ord(char) < 32 for char in name))
    name.encode("utf-8")


def archive_name(parts):
    require(len(parts) <= 32)
    name = "/".join(parts)
    require(len(name) <= 512)
    return name


def open_root(path):
    path = Path(path)
    require(path.is_absolute() and not path.is_symlink())
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(fd)
    require(stat.S_ISDIR(info.st_mode))
    return fd


def hash_file(fd, expected):
    require(fingerprint(os.fstat(fd)) == expected and os.fstat(fd).st_nlink == 1)
    digest = hashlib.sha256()
    size = 0
    while chunk := os.read(fd, CHUNK):
        size += len(chunk)
        require(size <= MAX_ARCHIVE_BYTES)
        digest.update(chunk)
    require(fingerprint(os.fstat(fd)) == expected)
    return size, digest.hexdigest()


def scan_root(root_fd, label, directories, files, records):
    device = os.fstat(root_fd).st_dev
    total = 0

    def walk(fd, relative):
        nonlocal total
        info = os.fstat(fd)
        require(info.st_dev == device and stat.S_ISDIR(info.st_mode))
        name = archive_name((label, *relative))
        directories[name] = fingerprint(info)
        records.append(("directory", name))
        require(len(records) <= MAX_ARCHIVE_FILES)
        for child in sorted(os.listdir(fd)):
            safe_name(child)
            parts = (*relative, child)
            archive = archive_name((label, *parts))
            before = os.stat(child, dir_fd=fd, follow_symlinks=False)
            require(before.st_dev == device)
            if stat.S_ISDIR(before.st_mode):
                next_fd = os.open(child, os.O_RDONLY | os.O_DIRECTORY |
                                  os.O_NOFOLLOW, dir_fd=fd)
                try:
                    require(fingerprint(os.fstat(next_fd)) == fingerprint(before))
                    walk(next_fd, parts)
                finally:
                    os.close(next_fd)
            else:
                require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1)
                file_fd = os.open(child, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    require(fingerprint(os.fstat(file_fd)) == fingerprint(before))
                    size, digest = hash_file(file_fd, fingerprint(before))
                finally:
                    os.close(file_fd)
                files[archive] = (label, parts, fingerprint(before), size, digest)
                records.append(("file", archive, size, digest))
                total += size
                require(len(records) <= MAX_ARCHIVE_FILES and total <= MAX_ARCHIVE_BYTES)
        require(fingerprint(os.fstat(fd)) == fingerprint(info))

    walk(root_fd, ())


def open_parent(root_fd, parts, directories, label):
    fd = os.dup(root_fd)
    try:
        require(fingerprint(os.fstat(fd)) == directories[label])
        for index, part in enumerate(parts):
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY |
                              os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            require(fingerprint(os.fstat(fd)) ==
                    directories[archive_name((label, *parts[:index + 1]))])
        return fd
    except BaseException:
        os.close(fd)
        raise


class HashingReader:
    def __init__(self, fd):
        self.fd = fd
        self.digest = hashlib.sha256()
        self.size = 0

    def read(self, count):
        data = os.read(self.fd, min(count, CHUNK))
        self.size += len(data)
        self.digest.update(data)
        return data


def tar_info(name, size=0, directory=False):
    info = tarfile.TarInfo(name + "/" if directory else name)
    info.type = tarfile.DIRTYPE if directory else tarfile.REGTYPE
    info.mode = 0o700 if directory else 0o600
    info.size = size
    info.mtime = 0
    return info


def emit(kind, source_sha, pod_uid, expected_uids, observation, roots, output):
    namespace = validate_observation(kind, source_sha, pod_uid,
                                     expected_uids, observation)
    require(set(roots) == set(ROOTS[kind]))
    opened = {}
    try:
        for label, path in roots.items():
            opened[label] = open_root(path)
        directories, files, records = {}, {}, []
        for label, fd in opened.items():
            scan_root(fd, label, directories, files, records)
        require(sum(item[3] for item in files.values()) <= MAX_ARCHIVE_BYTES)
        if kind == "operator":
            required = {"journal/journal.json", "bootstrap/output.json",
                        "bootstrap/initial-admin-password",
                        "bootstrap/initial-admin-service-key.json"}
            require(required <= set(files) and
                    all(files[name][3] > 0 for name in required))
        else:
            require(any(name.startswith("state/") and item[3] > 0
                        for name, item in files.items()))
        manifest = {"schemaVersion": 1, "sourceSha": source_sha,
                    "namespace": namespace, "readerPodUid": pod_uid,
                    "claimUids": expected_uids,
                    "payloadSha256": hashlib.sha256(canonical(sorted(records))).hexdigest()}
        manifest_bytes = canonical(manifest)
        with tarfile.open(fileobj=output, mode="w|", format=tarfile.PAX_FORMAT) as tar:
            tar.addfile(tar_info("manifest.json", len(manifest_bytes)),
                        io.BytesIO(manifest_bytes))
            for record in sorted(records):
                name = record[1]
                label = name.split("/", 1)[0]
                relative = tuple(name.split("/")[1:])
                if record[0] == "directory":
                    parent = open_parent(opened[label], relative, directories, label)
                    os.close(parent)
                    tar.addfile(tar_info(name, directory=True))
                    continue
                _, parts, expected, size, digest = files[name]
                parent = open_parent(opened[label], parts[:-1], directories, label)
                try:
                    fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW,
                                 dir_fd=parent)
                finally:
                    os.close(parent)
                try:
                    require(fingerprint(os.fstat(fd)) == expected and
                            os.fstat(fd).st_nlink == 1)
                    reader = HashingReader(fd)
                    tar.addfile(tar_info(name, size), reader)
                    require(reader.size == size and reader.digest.hexdigest() == digest)
                    os.lseek(fd, 0, os.SEEK_SET)
                    require(hash_file(fd, expected) == (size, digest))
                finally:
                    os.close(fd)
        for name, expected in directories.items():
            label, *parts = name.split("/")
            fd = open_parent(opened[label], tuple(parts), directories, label)
            os.close(fd)
        return manifest
    finally:
        for fd in opened.values():
            os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("operator", "tenant"), required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--reader-pod-uid", required=True)
    parser.add_argument("--journal-claim-uid")
    parser.add_argument("--bootstrap-claim-uid")
    parser.add_argument("--gateway-claim-uid")
    args = parser.parse_args(argv)
    expected = ({"journal": args.journal_claim_uid,
                 "bootstrap": args.bootstrap_claim_uid}
                if args.kind == "operator" else {"gateway": args.gateway_claim_uid})
    try:
        require(all(expected.values()) and
                (args.gateway_claim_uid is None if args.kind == "operator" else
                 args.journal_claim_uid is None and args.bootstrap_claim_uid is None))
        emit(args.kind, args.source_sha, args.reader_pod_uid, expected,
             read_observation(sys.stdin.buffer), ROOTS[args.kind],
             sys.stdout.buffer)
    except (Blocked, OSError, ValueError, TypeError, KeyError, UnicodeError,
            tarfile.TarError):
        print("Enterprise private reader archive blocked", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
