#!/usr/bin/env python3
"""Capture the stopped rscstore PVC; prove a separately retrieved archive."""

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading


ROOT = Path(__file__).resolve().parents[1]
SERVER = "https://10.1.0.199:6443"
NAMESPACE = "octelium"
DEPLOYMENT = "octeliumee-rscstore"
CLAIM = "octelium-rscstore"
INSPECTOR = "octelium-rscstore-capture-inspector"
IMAGE = "harbor.stinkyboi.com/mirror/docker.io/library/busybox:1.38.0@sha256:fd7dc98638c8e305f4dc34e979f1c0fdfdcaeb0fbf8fcff77ae834b6da3d7e6e"
PARTS = ("rscstore.part01", "rscstore.part02")
MAX_ARCHIVE = 10 * 1024**3
MAX_OBJECT = 5 * 1024**3
CHUNK = 1024 * 1024
UID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def write_new(path, data):
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def private_parent(path):
    require(path.is_absolute(), "destination must be absolute")
    require(not any(parent.is_symlink() for parent in (path, *path.parents)),
            "destination must not contain symlinks")
    path = path.resolve(strict=True)
    info = path.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700,
            "destination must be an owned mode-0700 directory")
    require(not any((parent / ".git").exists() for parent in (path, *path.parents)),
            "destination must be outside Git")
    temp_roots = (Path(tempfile.gettempdir()).resolve(), Path("/private/tmp"), Path("/tmp"))
    require(not any(path == root or root in path.parents for root in temp_roots),
            "destination must be durable, not temporary")
    require(local_mount(path), "destination must be on local off-NAS storage")
    return path


def local_mount(path):
    """Reject NFS/SMB and ephemeral mounts; the operator still owns durability."""
    mounts = []
    for line in subprocess.check_output(["mount"], text=True).splitlines():
        match = re.fullmatch(r"(.+) on (.+) type ([^ ]+) \(.*\)", line)
        if match:
            source, target, kind = match.groups()
        else:
            match = re.fullmatch(r"(.+) on (.+) \(([^,)]+)(?:,.*)?\)", line)
            if not match:
                continue
            source, target, kind = match.groups()
        mount_path = Path(target.replace(r"\040", " ")).resolve()
        if path == mount_path or mount_path in path.parents:
            mounts.append((len(mount_path.parts), source, kind.lower()))
    require(mounts, "destination mount could not be identified")
    _, source, kind = max(mounts)
    disallowed = ("nfs", "smb", "cifs", "afp", "fuse", "tmpfs", "ramfs", "overlay", "autofs", "devfs")
    return not kind.startswith(disallowed) and "10.1.0.2" not in source


def output(*command):
    return subprocess.check_output(command, text=True, timeout=45, stderr=subprocess.DEVNULL)


def json_output(*command):
    return json.loads(output(*command))


def release_guard(expected_sha, context):
    require(re.fullmatch(r"[0-9a-f]{40}", expected_sha or ""), "expected main SHA required")
    require(context and not context.startswith("-"), "explicit kubectl context required")
    require(output("git", "-C", str(ROOT), "rev-parse", "HEAD").strip() == expected_sha,
            "checkout differs from reviewed main")
    require(not output("git", "-C", str(ROOT), "status", "--porcelain").strip(),
            "checkout must be clean")
    require(output("gh", "api", "repos/Stuhlmuller/homelab/commits/main", "--jq", ".sha").strip()
            == expected_sha, "reviewed main has advanced")
    kustomization = ROOT / "clusters/homelab/apps/octelium-enterprise/kustomization.yaml"
    fenced_kustomization_guard(kustomization)
    config = json_output("kubectl", "--context", context, "config", "view", "--minify", "-o", "json")
    require(config["clusters"][0]["cluster"]["server"] == SERVER,
            "kubectl context points at another cluster")
    argo_guard(context, expected_sha)


def fenced_kustomization_guard(kustomization):
    require(kustomization.read_text().splitlines() == [
        "apiVersion: kustomize.config.k8s.io/v1beta1", "kind: Kustomization", "resources:",
        "  - emergency-dataplane.yaml", "  - resources.yaml", "  - capture-stage/inspector.yaml",
        "  - capture-stage/inspector-networkpolicy.yaml",
        "components:",
        "  - capture-stage"], "fenced capture source differs from reviewed shape")


def argo_guard(context, expected_sha):
    application = json_output("kubectl", "--context", context, "-n", "argocd", "get",
                              "application", "octelium-enterprise", "-o", "json")
    spec = application.get("spec", {})
    sync = application.get("status", {}).get("sync", {})
    sources = spec.get("sources")
    revisions = sync.get("revisions")
    require(spec.get("source") is None and sync.get("revision") is None
            and isinstance(sources, list) and len(sources) == 1
            and isinstance(sources[0], dict)
            and isinstance(revisions, list) and len(revisions) == 1,
            "Octelium Enterprise Argo CD sources or revisions changed")
    source = sources[0]
    require(set(source) == {"path", "targetRevision", "repoURL"}
            and source.get("path") == "clusters/homelab/apps/octelium-enterprise"
            and source.get("targetRevision") == "main"
            and source.get("repoURL") == "https://github.com/Stuhlmuller/homelab.git"
            and sync.get("status") == "Synced" and revisions[0] == expected_sha,
            "Octelium Enterprise Argo CD state is not synced to reviewed main")


def inspector_guard(deployment, pvc, pv, pods, expected_pvc_uid, expected_pv_uid):
    require(deployment["metadata"]["namespace"] == NAMESPACE
            and deployment["metadata"]["name"] == DEPLOYMENT,
            "wrong resource-store Deployment")
    require(deployment["spec"].get("replicas") == 0
            and deployment["status"].get("observedGeneration", 0) >= deployment["metadata"]["generation"]
            and all(deployment["status"].get(field, 0) == 0 for field in
                    ("replicas", "readyReplicas", "availableReplicas")),
            "resource-store writer is not fenced")
    require(UID.fullmatch(expected_pvc_uid or "") and UID.fullmatch(expected_pv_uid or ""),
            "exact PVC and PV UIDs required")
    require(pvc["metadata"]["namespace"] == NAMESPACE and pvc["metadata"]["name"] == CLAIM
            and pvc["metadata"]["uid"] == expected_pvc_uid
            and pvc["status"]["phase"] == "Bound"
            and pvc["spec"].get("storageClassName") == "nfs-default",
            "source PVC identity or binding changed")
    pv_name = pvc["spec"].get("volumeName")
    require(pv_name and pv["metadata"]["name"] == pv_name
            and pv["metadata"]["uid"] == expected_pv_uid
            and pv["status"]["phase"] == "Bound", "source PV identity changed")
    claim_ref = pv["spec"].get("claimRef", {})
    require(claim_ref.get("namespace") == NAMESPACE and claim_ref.get("name") == CLAIM
            and claim_ref.get("uid") == expected_pvc_uid, "source PV claim changed")
    active = [pod for pod in pods if pod["status"]["phase"] not in ("Succeeded", "Failed")]
    inspectors = [pod for pod in active if pod["metadata"]["name"] == INSPECTOR]
    require(len(inspectors) == 1, "exactly one inspector is required")
    inspector = inspectors[0]
    for pod in active:
        mounts_claim = any(volume.get("persistentVolumeClaim", {}).get("claimName") == CLAIM
                           for volume in pod["spec"].get("volumes", []))
        require(pod is inspector or not mounts_claim, "another active Pod mounts the PVC")
    metadata, spec, status = inspector["metadata"], inspector["spec"], inspector["status"]
    labels = metadata.get("labels", {})
    require(metadata["namespace"] == NAMESPACE and not metadata.get("deletionTimestamp")
            and not metadata.get("ownerReferences")
            and labels.get("app.kubernetes.io/name") == INSPECTOR
            and labels.get("app.kubernetes.io/part-of") == "octelium-enterprise"
            and not any(key in labels for key in
                        ("app", "octelium.com/app", "octelium.com/component",
                         "octelium.com/component-type")),
            "inspector identity changed")
    require(status["phase"] == "Running"
            and len(status.get("containerStatuses", [])) == 1
            and status["containerStatuses"][0]["ready"] is True,
            "inspector is not ready")
    require(spec.get("automountServiceAccountToken") is False
            and spec.get("enableServiceLinks") is False
            and not spec.get("initContainers") and not spec.get("ephemeralContainers")
            and spec.get("nodeSelector") == {"octelium.com/node-mode-controlplane": ""}
            and len(spec.get("containers", [])) == 1 and len(spec.get("volumes", [])) == 1,
            "inspector Pod shape changed")
    container, volume = spec["containers"][0], spec["volumes"][0]
    require(container["name"] == "inspection" and container["image"] == IMAGE
            and container.get("command") == ["/bin/sh", "-ec", "exec sleep infinity"]
            and not container.get("env") and not container.get("envFrom")
            and len(container.get("volumeMounts", [])) == 1,
            "inspector command or credentials changed")
    probe_fields = {"exec", "initialDelaySeconds", "periodSeconds", "timeoutSeconds",
                    "failureThreshold", "successThreshold"}
    for probe, command, period in (
            (container.get("livenessProbe"), "test -d /source", 30),
            (container.get("readinessProbe"),
             "test -f /source/store.db && test -r /source/store.db", 10)):
        require(isinstance(probe, dict) and set(probe) <= probe_fields
                and probe.get("exec") == {"command": ["/bin/sh", "-ec", command]}
                and probe.get("periodSeconds") == period and probe.get("timeoutSeconds") == 2
                and probe.get("initialDelaySeconds", 0) == 0
                and probe.get("failureThreshold", 3) == 3
                and probe.get("successThreshold", 1) == 1,
                "inspector health probe changed")
    mount = container["volumeMounts"][0]
    require(mount == {"name": "source", "mountPath": "/source", "readOnly": True}
            and volume == {"name": "source", "persistentVolumeClaim": {
                "claimName": CLAIM, "readOnly": True}},
            "inspector PVC mount is not read-only")
    security = container.get("securityContext", {})
    require(security.get("runAsUser") == 0 and security.get("runAsGroup") == 0
            and security.get("readOnlyRootFilesystem") is True
            and security.get("allowPrivilegeEscalation") is False
            and security.get("capabilities", {}).get("drop") == ["ALL"]
            and spec.get("securityContext", {}).get("seccompProfile", {}).get("type") == "RuntimeDefault",
            "inspector security context changed")
    return {"pvc_uid": expected_pvc_uid, "pv_name": pv_name,
            "pv_uid": expected_pv_uid, "deployment_uid": deployment["metadata"]["uid"],
            "inspector_uid": metadata["uid"]}


def cluster_guard(context, pvc_uid, pv_uid, expected_sha):
    argo_guard(context, expected_sha)
    prefix = ("kubectl", "--context", context, "-n", NAMESPACE)
    deployment = json_output(*prefix, "get", "deployment", DEPLOYMENT, "-o", "json")
    pvc = json_output(*prefix, "get", "pvc", CLAIM, "-o", "json")
    pv_name = pvc["spec"].get("volumeName")
    require(pv_name, "source PVC is not bound")
    pv = json_output("kubectl", "--context", context, "get", "pv", pv_name, "-o", "json")
    pod_list = json_output(*prefix, "get", "pods", "--chunk-size=0", "-o", "json")
    require(pod_list.get("apiVersion") == "v1" and pod_list.get("kind") == "PodList"
            and isinstance(pod_list.get("items"), list)
            and isinstance(pod_list.get("metadata", {}).get("resourceVersion"), str)
            and pod_list["metadata"]["resourceVersion"]
            and not pod_list["metadata"].get("continue"),
            "namespaced PodList is incomplete")
    pods = pod_list["items"]
    return inspector_guard(deployment, pvc, pv, pods, pvc_uid, pv_uid)


def tar_stream(context, pod, sink=None):
    command = ["kubectl", "--context", context, "-n", NAMESPACE, "exec", pod,
               "-c", "inspection", "--", "tar", "-C", "/source", "-cf", "-", "."]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    timer = threading.Timer(7200, process.kill)
    timer.start()
    digest, size = hashlib.sha256(), 0
    try:
        while chunk := process.stdout.read(CHUNK):
            size += len(chunk)
            require(size <= MAX_ARCHIVE, "PVC archive exceeds bounded publication size")
            digest.update(chunk)
            if sink:
                sink(chunk)
        require(process.wait(timeout=15) == 0, "PVC tar stream failed")
        require(size >= 1024, "PVC tar stream is incomplete")
        return {"bytes": size, "sha256": digest.hexdigest()}
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        timer.cancel()
        process.stdout.close()


class PartsReader:
    def __init__(self, directory):
        self.stack = ExitStack()
        self.files = [self.stack.enter_context((directory / name).open("rb")) for name in PARTS]
        self.index = 0

    def read(self, size=-1):
        if size < 0:
            size = CHUNK
        result = bytearray()
        while len(result) < size and self.index < len(self.files):
            chunk = self.files[self.index].read(size - len(result))
            if chunk:
                result.extend(chunk)
            else:
                self.index += 1
        return bytes(result)

    def close(self):
        self.stack.close()


def hash_parts(directory):
    digest, total = hashlib.sha256(), 0
    for name in PARTS:
        path = directory / name
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and 0 < info.st_size <= MAX_OBJECT, "invalid archive part")
        with path.open("rb") as stream:
            while chunk := stream.read(CHUNK):
                digest.update(chunk)
                total += len(chunk)
    require(total <= MAX_ARCHIVE, "PVC archive exceeds publication size")
    require(total % 512 == 0, "PVC tar blocks are incomplete")
    with (directory / PARTS[-1]).open("rb") as last:
        last.seek(-1024, os.SEEK_END)
        require(last.read(1024) == bytes(1024), "PVC tar trailer is incomplete")
    return {"bytes": total, "sha256": digest.hexdigest()}


def inspect_archive(directory, restore=None):
    seen, tree = set(), hashlib.sha256()
    files, bytes_total = 0, 0
    recovery_artifacts = {}
    reader = PartsReader(directory)
    try:
        with tarfile.open(fileobj=reader, mode="r|") as archive:
            for member in archive:
                name = member.name
                path = PurePosixPath(name)
                require(name == "." or name.startswith("./"), "archive path is not rooted at PVC")
                require(not path.is_absolute() and ".." not in path.parts and "\\" not in name,
                        "unsafe archive path")
                relative = str(path)
                require(relative not in seen, "duplicate archive path")
                seen.add(relative)
                require(member.isdir() or member.isfile(), "PVC has unsupported file type")
                target = restore.joinpath(*path.parts) if restore else None
                if member.isdir():
                    if target:
                        target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    tree.update(canonical([relative, "directory", member.mode]))
                    continue
                files += 1
                bytes_total += member.size
                source = archive.extractfile(member)
                require(source is not None, "archive member cannot be read")
                digest = hashlib.sha256()
                if target:
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    output_file = target.open("xb")
                    os.chmod(target, 0o600)
                else:
                    output_file = None
                try:
                    while chunk := source.read(CHUNK):
                        digest.update(chunk)
                        if output_file:
                            output_file.write(chunk)
                    if output_file:
                        output_file.flush()
                        os.fsync(output_file.fileno())
                finally:
                    if output_file:
                        output_file.close()
                if target:
                    with target.open("rb") as reopened:
                        require(hashlib.file_digest(reopened, "sha256").hexdigest() == digest.hexdigest(),
                                "isolated extracted file differs from archive")
                if path.name.startswith("store.db.wal") or path.name.startswith(
                        ".homelab-rscstore-wal-recovery"):
                    recovery_artifacts[relative] = digest.hexdigest()
                tree.update(canonical([relative, "file", member.mode, member.size, digest.hexdigest()]))
        require(files > 0, "PVC archive contains no regular files")
        require("store.db" in seen, "PVC archive lacks the resource-store database")
        return {"file_count": files, "file_bytes": bytes_total,
                "tree_sha256": tree.hexdigest(),
                "recovery_artifacts": dict(sorted(recovery_artifacts.items()))}
    finally:
        reader.close()


def validate_bundle(directory, record=None):
    if record is None:
        record = json.loads((directory / "capture.json").read_text())
    require(record.get("format") == 1 and record.get("capture_method") == "complete-pvc-tar-v1"
            and re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", record.get("captured_at", ""))
            and record.get("writers_fenced") is True
            and re.fullmatch(r"[0-9a-f]{40}", record.get("approved_fence_reference", "")),
            "invalid stopped-writer capture receipt")
    source = record.get("source", {})
    require(source.get("namespace") == NAMESPACE and source.get("pvc_name") == CLAIM
            and all(UID.fullmatch(source.get(key, "")) for key in
                    ("pvc_uid", "pv_uid", "deployment_uid", "inspector_uid"))
            and isinstance(source.get("pv_name"), str) and source["pv_name"],
            "invalid source identity receipt")
    archive = record.get("archive", {})
    require(archive.get("parts") == list(PARTS)
            and type(archive.get("bytes")) is int and 0 < archive["bytes"] <= MAX_ARCHIVE
            and all(SHA.fullmatch(archive.get(key, "")) for key in
                    ("before_sha256", "sha256", "after_sha256"))
            and archive["before_sha256"] == archive["sha256"] == archive["after_sha256"],
            "PVC changed across capture")
    require(hash_parts(directory) == {"bytes": archive["bytes"], "sha256": archive["sha256"]},
            "archive parts differ from source receipt")
    inspection = inspect_archive(directory)
    require(inspection == record.get("inspection"), "archive tree differs from source receipt")
    return record


def capture(workspace, expected_sha, context, pvc_uid, pv_uid):
    workspace = private_parent(workspace)
    release_guard(expected_sha, context)
    source = cluster_guard(context, pvc_uid, pv_uid, expected_sha)
    pod = INSPECTOR
    before = tar_stream(context, pod)
    require(cluster_guard(context, pvc_uid, pv_uid, expected_sha) == source,
            "cluster identity changed after preflight")
    require(shutil.disk_usage(workspace).free > before["bytes"] * 5 + 64 * 1024**2,
            "off-NAS workspace lacks space for capture, publication and proof")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = workspace / (".partial-" + stamp)
    complete = workspace / stamp
    require(not complete.exists(), "capture version already exists")
    directory.mkdir(mode=0o700, exist_ok=False)
    threshold = (before["bytes"] + 1) // 2
    written = [0, 0]
    with (directory / PARTS[0]).open("xb") as first, (directory / PARTS[1]).open("xb") as second:
        for path in (directory / PARTS[0], directory / PARTS[1]):
            os.chmod(path, 0o600)

        def sink(chunk):
            remaining = threshold - written[0]
            left = chunk[:remaining]
            right = chunk[remaining:]
            first.write(left)
            second.write(right)
            written[0] += len(left)
            written[1] += len(right)

        archive = tar_stream(context, pod, sink)
        for stream in (first, second):
            stream.flush()
            os.fsync(stream.fileno())
    require(archive == before and written == [threshold, before["bytes"] - threshold],
            "source changed during archive stream")
    require(cluster_guard(context, pvc_uid, pv_uid, expected_sha) == source,
            "cluster identity changed during archive stream")
    after = tar_stream(context, pod)
    require(after == before and cluster_guard(context, pvc_uid, pv_uid, expected_sha) == source,
            "source or cluster identity changed after archive stream")
    inspection = inspect_archive(directory)
    record = {"format": 1, "capture_method": "complete-pvc-tar-v1", "captured_at": stamp,
              "writers_fenced": True, "approved_fence_reference": expected_sha,
              "source": {"namespace": NAMESPACE, "pvc_name": CLAIM, **source},
              "archive": {"parts": list(PARTS), "bytes": archive["bytes"],
                          "before_sha256": before["sha256"], "sha256": archive["sha256"],
                          "after_sha256": after["sha256"]},
              "inspection": inspection}
    validate_bundle(directory, record)
    write_new(directory / "capture.json", canonical(record))
    hashes = []
    for name in (*PARTS, "capture.json"):
        with (directory / name).open("rb") as stream:
            hashes.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {name}\n")
    write_new(directory / "SHA256SUMS", "".join(hashes).encode())
    fsync_directory(directory)
    require(cluster_guard(context, pvc_uid, pv_uid, expected_sha) == source,
            "source or cluster identity changed before receipt")
    release_guard(expected_sha, context)
    directory.rename(complete)
    fsync_directory(workspace)
    return stamp


def prove_retrieval(workspace, identifier, proof, aws_cli, profile):
    """Only publisher-verified, freshly downloaded S3 versions can get proof."""
    workspace = private_parent(workspace)
    require(re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{64}", identifier or ""),
            "exact published backup ID required")
    require(proof.is_absolute() and private_parent(proof.parent) == workspace
            and not proof.exists(),
            "new proof directory must be inside the private workspace")
    require(aws_cli.is_absolute(), "AWS CLI path must be absolute")
    command = [sys.executable, "-I", str(ROOT / "scripts/application-backup.py"), "retrieve",
               "--app", "octelium-rscstore", "--workspace", str(workspace), "--id", identifier,
               "--profile", profile, "--aws-cli", str(aws_cli)]
    name = subprocess.check_output(command, text=True, timeout=7200,
                                   stderr=subprocess.DEVNULL).strip()
    require(re.fullmatch(r"retrieval-[A-Za-z0-9_-]+", name),
            "publisher returned an invalid retrieval directory")
    prove_downloaded_bundle(workspace / name, proof, identifier)


def prove_downloaded_bundle(retrieval, proof, expected_id):
    require(retrieval.is_absolute() and proof.is_absolute(), "private paths must be absolute")
    require(not retrieval.is_symlink(), "retrieval must not be a symlink")
    retrieval = retrieval.resolve(strict=True)
    private_parent(retrieval.parent)
    private_parent(proof.parent)
    info = retrieval.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700,
            "retrieval must be an owned mode-0700 directory")
    require(not proof.exists(), "proof directory already exists")
    marker = json.loads((retrieval / "complete.json").read_text())
    receipt = json.loads((retrieval / "retrieval.json").read_text())
    identifier = receipt.get("id", "")
    require(identifier == expected_id and marker.get("app") == "octelium-rscstore"
            and re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{64}", identifier)
            and marker.get("captured_at") == identifier[:16]
            and isinstance(receipt.get("marker_version"), str)
            and receipt["marker_version"] not in ("", "null"),
            "retrieval is not versioned rscstore data")
    objects = marker.get("objects", {})
    require(set(objects) == {*PARTS, "capture.json"}, "retrieval has incomplete object set")
    for name, item in objects.items():
        require(isinstance(item.get("version_id"), str) and item["version_id"] not in ("", "null"),
                "retrieval object has no version")
        with (retrieval / name).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        require(item["digest"] == {"bytes": (retrieval / name).stat().st_size, "sha256": digest},
                "retrieved object differs from versioned marker")
    record = validate_bundle(retrieval)
    proof.mkdir(mode=0o700)
    restored = proof / "restored"
    restored.mkdir(mode=0o700)
    inspection = inspect_archive(retrieval, restored)
    require(inspection == record["inspection"], "isolated archive extraction differs")
    restored_files = 0
    for path in restored.rglob("*"):
        require(path.is_file() or path.is_dir(), "isolated extraction contains special file")
        if path.is_file():
            restored_files += 1
    require(restored_files == inspection["file_count"], "isolated extraction is incomplete")
    write_new(proof / "proof.json", canonical({
        "format": 1, "capture_id": identifier,
        "marker_version": receipt["marker_version"],
        "object_versions": {name: item["version_id"] for name, item in objects.items()},
        "archive_sha256": record["archive"]["sha256"],
        "inspection": inspection, "proof": "isolated-file-extraction-only",
    }))
    fsync_directory(proof)
    fsync_directory(proof.parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture_command = commands.add_parser("capture")
    capture_command.add_argument("--workspace", type=Path, required=True)
    capture_command.add_argument("--expected-sha", required=True)
    capture_command.add_argument("--context", required=True)
    capture_command.add_argument("--expected-pvc-uid", required=True)
    capture_command.add_argument("--expected-pv-uid", required=True)
    proof_command = commands.add_parser("prove-retrieval")
    proof_command.add_argument("--workspace", type=Path, required=True)
    proof_command.add_argument("--id", required=True)
    proof_command.add_argument("--proof", type=Path, required=True)
    proof_command.add_argument("--aws-cli", type=Path, required=True)
    proof_command.add_argument("--profile", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "capture":
            stamp = capture(args.workspace, args.expected_sha, args.context,
                            args.expected_pvc_uid, args.expected_pv_uid)
            print(f"Private PVC capture complete: {stamp}. Publish and retrieve before recovery review.")
        else:
            prove_retrieval(args.workspace, args.id, args.proof, args.aws_cli, args.profile)
            print("Versioned archive extraction proof complete; DuckDB reopen remains unverified.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, IndexError, tarfile.TarError,
            subprocess.SubprocessError):
        print("Rscstore capture/proof failed; retain private scratch and keep the writer fenced.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
