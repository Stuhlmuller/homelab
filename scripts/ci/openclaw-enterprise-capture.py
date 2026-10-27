#!/usr/bin/env python3
"""Assemble a private, unpublishable Enterprise recovery tree from reader archives.

This source-only boundary does not fetch live observations, authorize a stop,
prove continuous writer exclusion, dispatch Jobs, or publish a backup. A future
protected coordinator must supply fresh authenticated observations and a
continuous fence before the backup packager can use the staged tree.
"""

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("oce_capture_reconciler",
                                               ROOT / "scripts/openclaw-enterprise.py")
OCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OCE)
SHA = re.compile(r"[0-9a-f]{40}\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
UID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
DNS = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z")
SYSTEM_KEYS = {
    "occ-postgres-root": ("tls.crt", "tls.key"),
    "occ-postgres-admin": ("password",),
    "occ-postgres-migrator": ("password",),
    "occ-postgres-app": ("password",),
    "occ-postgres-backup": ("password",),
    "occ-auth": ("secret",),
    "occ-private-gateway-key": ("occ",),
    "occ-gateway-654a256bceae-root": ("tls.crt", "tls.key"),
}
CONTROL_OUTPUT = {
    ("occ-postgres-root", "tls.crt"): "postgres-root/tls.crt",
    ("occ-postgres-root", "tls.key"): "postgres-root/tls.key",
    ("occ-postgres-admin", "password"): "postgres-admin/password",
    ("occ-postgres-migrator", "password"): "postgres-migrator/password",
    ("occ-postgres-app", "password"): "postgres-app/password",
    ("occ-postgres-backup", "password"): "postgres-backup/password",
    ("occ-auth", "secret"): "auth/secret",
    ("occ-private-gateway-key", "occ"): "gateway/occ",
    ("occ-gateway-654a256bceae-root", "tls.crt"): "gateway-ca/tls.crt",
    ("occ-gateway-654a256bceae-root", "tls.key"): "gateway-ca/tls.key",
}
MAX_ARCHIVE_BYTES = 16 * 1024 ** 3
MAX_ARCHIVE_FILES = 100_000
SCRATCH_RESERVE_BYTES = 2 * 1024 ** 3


class Blocked(RuntimeError):
    pass


def require(condition, message="Enterprise capture input is incomplete or changed"):
    if not condition:
        raise Blocked(message)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError):
        raise Blocked("Enterprise capture JSON is invalid") from None


def payload_digest(files, directories=()):
    """Commit payload file bytes and explicit directory paths, excluding manifest."""
    records = []
    for path, data in files.items():
        require(isinstance(path, str) and isinstance(data, bytes))
        records.append(("file", str(_archive_path(path)), len(data),
                        hashlib.sha256(data).hexdigest()))
    for path in directories:
        require(isinstance(path, str))
        records.append(("directory", str(_archive_path(path))))
    require(len({record[1] for record in records}) == len(records))
    return hashlib.sha256(canonical(sorted(records))).hexdigest()


def private_file(path):
    path = Path(path)
    require(path.is_absolute() and path.parent.resolve() == path.parent,
            "Enterprise capture input path is unsafe")
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and
            stat.S_IMODE(info.st_mode) & 0o077 == 0,
            "Enterprise capture input file permissions are unsafe")
    return path


def read_json(path, maximum=8 * 1024 * 1024):
    path = private_file(path)
    require(path.stat().st_size <= maximum, "Enterprise capture JSON is oversized")
    try:
        return json.loads(path.read_bytes())
    except (OSError, UnicodeError, ValueError):
        raise Blocked("Enterprise capture JSON is invalid") from None


def _archive_path(name):
    require(isinstance(name, str) and 1 <= len(name) <= 512 and "\\" not in name and
            "\x00" not in name)
    path = PurePosixPath(name)
    require(not path.is_absolute() and all(part not in ("", ".", "..")
                                           for part in name.split("/")) and
            len(path.parts) <= 32)
    return path


def _checked_member(member, seen):
    require(not getattr(member, "sparse", None) and
            not any(key.startswith("GNU.sparse") for key in member.pax_headers) and
            (member.type in (tarfile.REGTYPE, tarfile.AREGTYPE) or member.isdir()),
            "Enterprise reader archive has unsafe entries")
    require(not member.isdir() or member.size == 0,
            "Enterprise reader archive has unsafe directory metadata")
    path = _archive_path(member.name.rstrip("/") if member.isdir() else member.name)
    require(len(seen) < MAX_ARCHIVE_FILES and str(path) not in seen,
            "Enterprise reader archive has duplicate or too many entries")
    seen.add(str(path))
    return path


def declared_archive_bytes(archive):
    """Bound both inputs and reserve private scratch before extracting either."""
    archive = private_file(archive)
    require(archive.stat().st_size <= MAX_ARCHIVE_BYTES + 128 * 1024 ** 2,
            "Enterprise reader archive is oversized")
    try:
        with tarfile.open(archive, "r:*") as source:
            total = 0
            seen = set()
            for member in source:
                _checked_member(member, seen)
                if member.isfile():
                    require(0 <= member.size <= MAX_ARCHIVE_BYTES)
                    total += member.size
                    require(total <= MAX_ARCHIVE_BYTES)
            return total
    except (OSError, tarfile.TarError, EOFError, ValueError):
        raise Blocked("Enterprise reader archive is invalid") from None


def extract_reader(archive, destination):
    """Extract only bounded regular files and directories; never use tar extractall."""
    archive = private_file(archive)
    require(archive.stat().st_size <= MAX_ARCHIVE_BYTES + 128 * 1024 ** 2,
            "Enterprise reader archive is oversized")
    seen, files, total = set(), {}, 0
    try:
        with tarfile.open(archive, "r:*") as source:
            for member in source:
                path = _checked_member(member, seen)
                target = destination.joinpath(*path.parts)
                require(destination in target.parents)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    target.chmod(0o700)
                    files[str(path)] = None
                    continue
                require(member.size >= 0 and member.size <= MAX_ARCHIVE_BYTES and
                        len(files) < MAX_ARCHIVE_FILES)
                total += member.size
                require(total <= MAX_ARCHIVE_BYTES, "Enterprise reader archive is oversized")
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                source_file = source.extractfile(member)
                require(source_file is not None)
                digest = hashlib.sha256()
                copied = 0
                with target.open("xb") as output:
                    os.chmod(target, 0o600)
                    while chunk := source_file.read(1024 * 1024):
                        copied += len(chunk)
                        require(copied <= member.size)
                        digest.update(chunk)
                        output.write(chunk)
                require(copied == member.size)
                files[str(path)] = (copied, digest.hexdigest())
    except (OSError, tarfile.TarError, EOFError, ValueError):
        raise Blocked("Enterprise reader archive is invalid") from None
    return files


def _reader_manifest(root, files, expected_sha, namespace, pod_uid, claims, kind):
    manifest = read_json(root / "manifest.json", maximum=1024 * 1024)
    require(isinstance(manifest, dict) and set(manifest) == {
        "schemaVersion", "sourceSha", "namespace", "readerPodUid",
        "claimUids", "payloadSha256"} and manifest["schemaVersion"] == 1 and
        manifest["sourceSha"] == expected_sha and manifest["namespace"] == namespace and
        manifest["readerPodUid"] == pod_uid and manifest["claimUids"] == claims and
        isinstance(manifest["payloadSha256"], str) and
        HEX.fullmatch(manifest["payloadSha256"]))
    payload = {name: values for name, values in files.items() if name != "manifest.json"}
    require(len(payload) + 1 == len(files))
    records = [("directory", name) if values is None else
               ("file", name, values[0], values[1])
               for name, values in payload.items()]
    digest = hashlib.sha256(canonical(sorted(records))).hexdigest()
    require(manifest["payloadSha256"] == digest,
            "Enterprise reader bytes differ from private manifest")
    if kind == "operator":
        require(all((name in ("journal", "bootstrap") and values is None) or
                    name.startswith(("journal/", "bootstrap/"))
                    for name, values in payload.items()) and
                {"journal/journal.json", "bootstrap/output.json",
                 "bootstrap/initial-admin-password",
                 "bootstrap/initial-admin-service-key.json"} <= set(payload))
        require(all(payload[name] is not None and payload[name][0] > 0 for name in (
            "journal/journal.json", "bootstrap/output.json",
            "bootstrap/initial-admin-password",
            "bootstrap/initial-admin-service-key.json")))
    else:
        require(all((name == "state" and values is None) or
                    name.startswith("state/") for name, values in payload.items()) and
                any(name.startswith("state/") and values is not None and values[0] > 0
                    for name, values in payload.items()))
    return manifest


def _pod_list(value, expected=None):
    require(isinstance(value, dict) and value.get("kind") == "PodList" and
            isinstance(value.get("metadata"), dict) and
            isinstance(value["metadata"].get("resourceVersion"), str) and
            bool(value["metadata"]["resourceVersion"]) and
            value["metadata"].get("continue") in (None, "") and
            isinstance(value.get("items"), list))
    if expected is None:
        require(value["items"] == [], "Enterprise tenant writer fence is absent")
    else:
        require(value["items"] == [expected],
                "Enterprise tenant reader is not the only Pod")


def _reader_pod(pod, namespace, uid, claims):
    metadata = pod.get("metadata") if isinstance(pod, dict) else None
    spec = pod.get("spec") if isinstance(pod, dict) else None
    require(isinstance(metadata, dict) and metadata.get("namespace") == namespace and
            isinstance(metadata.get("name"), str) and DNS.fullmatch(metadata["name"]) and
            isinstance(uid, str) and UID.fullmatch(uid) and
            metadata.get("uid") == uid and isinstance(spec, dict) and
            spec.get("automountServiceAccountToken") is False and
            spec.get("hostNetwork") is False and spec.get("restartPolicy") == "Never" and
            spec.get("hostPID") in (None, False) and
            spec.get("hostIPC") in (None, False) and
            spec.get("initContainers") in (None, []) and
            spec.get("ephemeralContainers") in (None, []) and
            spec.get("securityContext") == {
                "runAsUser": 1000, "runAsNonRoot": True,
                "seccompProfile": {"type": "RuntimeDefault"}} and
            isinstance(spec.get("volumes"), list) and
            isinstance(spec.get("containers"), list) and len(spec["containers"]) == 1 and
            isinstance(spec["containers"][0], dict))
    require(spec["containers"][0].get("securityContext") == {
        "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]}})
    mounted = {item.get("name"): item.get("persistentVolumeClaim")
               for item in spec["volumes"] if isinstance(item, dict)}
    require(len(spec["volumes"]) == len(claims) and set(mounted) == set(claims) and all(
        mounted[key] == {"claimName": value, "readOnly": True}
        for key, value in claims.items()))
    mounts = {item.get("name"): item for item in spec["containers"][0].get("volumeMounts", [])
              if isinstance(item, dict)}
    require(len(spec["containers"][0].get("volumeMounts", [])) == len(claims) and
            set(mounts) == set(claims) and all(
                mounts[key] == {"name": key, "mountPath": "/source/" + key,
                                "readOnly": True} for key in claims))


def _claim(snapshot, key, namespace, name, storage_class, ownership=None):
    claims, volumes = snapshot.get("claims"), snapshot.get("volumes")
    require(isinstance(claims, dict) and isinstance(volumes, dict))
    claim = claims.get(key)
    volume = volumes.get(key)
    metadata = claim.get("metadata") if isinstance(claim, dict) else None
    spec = claim.get("spec") if isinstance(claim, dict) else None
    require(isinstance(metadata, dict) and isinstance(spec, dict) and
            metadata.get("namespace") == namespace and metadata.get("name") == name and
            isinstance(metadata.get("uid"), str) and UID.fullmatch(metadata["uid"]) and
            isinstance(metadata.get("resourceVersion"), str) and
            bool(metadata["resourceVersion"]) and
            metadata.get("deletionTimestamp") is None and
            spec.get("storageClassName") == storage_class and
            spec.get("accessModes") == ["ReadWriteOnce"] and
            isinstance(spec.get("volumeName"), str) and
            bool(spec["volumeName"]) and
            isinstance(claim.get("status"), dict) and
            claim["status"].get("phase") == "Bound")
    vm = volume.get("metadata") if isinstance(volume, dict) else None
    vs = volume.get("spec") if isinstance(volume, dict) else None
    require(isinstance(vm, dict) and isinstance(vs, dict) and
            vm.get("name") == spec["volumeName"] and
            isinstance(vm.get("uid"), str) and UID.fullmatch(vm["uid"]) and
            isinstance(vm.get("resourceVersion"), str) and bool(vm["resourceVersion"]) and
            vm.get("deletionTimestamp") is None and
            isinstance(vs.get("claimRef"), dict) and
            vs["claimRef"].get("uid") == metadata["uid"] and
            vs["claimRef"].get("name") == name and
            vs["claimRef"].get("namespace") == namespace and
            vs.get("storageClassName") == storage_class and
            vs.get("persistentVolumeReclaimPolicy") == "Retain")
    if ownership is not None:
        namespace_id, agent_id = ownership
        labels = metadata.get("labels")
        annotations = metadata.get("annotations")
        require(isinstance(labels, dict) and isinstance(annotations, dict) and
                labels.get("app.kubernetes.io/managed-by") == "openclaw-enterprise" and
                labels.get("openclaw.dev/namespace") == namespace_id and
                labels.get("openclaw.dev/agent") == agent_id and
                annotations.get("openclaw.dev/namespace-id") == namespace_id and
                annotations.get("openclaw.dev/agent-id") == agent_id and
                spec.get("volumeMode") == "Filesystem" and
                spec.get("resources", {}).get("requests", {}).get("storage") == "10Gi",
                "Enterprise gateway claim ownership changed")
    return metadata["uid"]


def _secret_list(value, namespace):
    require(isinstance(value, dict) and value.get("kind") == "SecretList" and
            isinstance(value.get("metadata"), dict) and
            isinstance(value["metadata"].get("resourceVersion"), str) and
            bool(value["metadata"]["resourceVersion"]) and
            value["metadata"].get("continue") in (None, "") and
            isinstance(value.get("items"), list))
    result, seen_uids = {}, set()
    for item in value["items"]:
        metadata = item.get("metadata") if isinstance(item, dict) else None
        require(isinstance(metadata, dict) and item.get("kind") == "Secret" and
                metadata.get("namespace") == namespace and
                isinstance(metadata.get("name"), str) and DNS.fullmatch(metadata["name"]) and
                isinstance(metadata.get("uid"), str) and UID.fullmatch(metadata["uid"]) and
                isinstance(metadata.get("resourceVersion"), str) and
                bool(metadata["resourceVersion"]) and
                isinstance(metadata.get("labels", {}), dict) and
                isinstance(metadata.get("annotations", {}), dict) and
                isinstance(item.get("data"), dict) and item["data"] and
                metadata["name"] not in result and metadata["uid"] not in seen_uids)
        for encoded in item["data"].values():
            require(isinstance(encoded, str))
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except (ValueError, base64.binascii.Error):
                raise Blocked("Enterprise Secret value encoding is invalid") from None
            require(decoded and base64.b64encode(decoded).decode() == encoded)
        result[metadata["name"]] = item
        seen_uids.add(metadata["uid"])
    return result


def _secret_value(item, key):
    data = item.get("data", {})
    if item.get("metadata", {}).get("name") in (
            "occ-postgres-root", "occ-gateway-654a256bceae-root"):
        require({"tls.crt", "tls.key"} <= set(data) and
                set(data) <= {"tls.crt", "tls.key", "ca.crt"})
    else:
        require(set(data) == {key})
    return base64.b64decode(item["data"][key], validate=True)


def _stopped(snapshot, state):
    agent, deployment, runtime = (snapshot.get(key) for key in
                                  ("agent", "deployment", "runtime"))
    require(isinstance(agent, dict) and agent.get("id") == state["agentId"] and
            agent.get("namespaceId") == state["namespaceId"] and
            agent.get("configurationId") == state["configurationId"] and
            agent.get("desiredRuntimeState") == "stopped" and
            agent.get("activeRevisionId") is None and
            isinstance(deployment, dict) and
            deployment.get("deploymentId") == state["revisionId"] and
            deployment.get("namespaceId") == state["namespaceId"] and
            deployment.get("agentId") == state["agentId"] and
            deployment.get("status") == "succeeded" and
            isinstance(runtime, dict) and runtime.get("revisionId") == state["revisionId"] and
            isinstance(runtime.get("observedAt"), str) and runtime["observedAt"] and
            runtime.get("pods") == [],
            "Enterprise Agent stop was not observed")
    _pod_list(snapshot.get("tenantPods"))


def _write_bytes(root, relative, data):
    require(isinstance(data, bytes) and data)
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with target.open("xb") as output:
        output.write(data)
    target.chmod(0o600)


def _move_tree(root, relative, source):
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    require(source.is_dir() and not source.is_symlink() and
            not target.exists() and not target.is_symlink())
    os.replace(source, target)


def assemble(config, expected_sha, observations, operator_archive, tenant_archive, output):
    """Create one local tree after two snapshots; fence continuity stays false."""
    OCE._validate_config(config)
    operator_contract = config.get("journalOperator")
    require(isinstance(operator_contract, dict) and
            operator_contract.get("enabled") is True and
            config.get("gatewayIdentity", {}).get("caSecretName") ==
            "occ-gateway-654a256bceae-root" and
            all(isinstance(operator_contract.get(key), str) and
                UID.fullmatch(operator_contract[key]) for key in
                ("journalClaimUid", "journalVolumeUid", "bootstrapClaimUid")),
            "Enterprise operator claim identities are not selected")
    require(isinstance(expected_sha, str) and SHA.fullmatch(expected_sha) and
            isinstance(observations, dict) and set(observations) == {
                "schemaVersion", "sourceSha", "identity", "before", "after",
                "readers", "duringTenantPods"} and
            observations["schemaVersion"] == 1 and
            observations["sourceSha"] == expected_sha)
    output = Path(output)
    require(output.is_absolute() and not output.exists() and not output.is_symlink())
    parent = output.parent
    parent_info = parent.lstat()
    require(parent.resolve() == parent and stat.S_ISDIR(parent_info.st_mode) and
            parent_info.st_uid == os.getuid() and
            stat.S_IMODE(parent_info.st_mode) & 0o077 == 0,
            "Enterprise capture output parent is not private")
    required_bytes = (declared_archive_bytes(operator_archive) +
                      declared_archive_bytes(tenant_archive) + SCRATCH_RESERVE_BYTES)
    volume = os.statvfs(parent)
    require(volume.f_bavail * volume.f_frsize >= required_bytes,
            "Enterprise private scratch capacity is insufficient")
    scratch = Path(tempfile.mkdtemp(prefix=".oce-capture-", dir=parent))
    try:
        operator_root, tenant_root, material = (scratch / name for name in
                                                ("operator", "tenant", "material"))
        for directory in (operator_root, tenant_root, material):
            directory.mkdir(mode=0o700)
        operator_files = extract_reader(operator_archive, operator_root)
        tenant_files = extract_reader(tenant_archive, tenant_root)
        state, _ = OCE.read_journal(operator_root / "journal/journal.json",
                                    config["source"]["revision"], OCE._identity_hash(config))
        required_state = ("installationId", "namespaceId", "agentId", "revisionId",
                          "configurationId", "secretId")
        require(all(isinstance(state.get(key), str) and state[key] for key in required_state) and
                state.get("pending") is None and
                observations.get("identity") == {key: state[key] for key in
                                                 ("installationId", "namespaceId",
                                                  "agentId", "revisionId")})
        before, after = observations["before"], observations["after"]
        require(isinstance(before, dict) and isinstance(after, dict))
        gateway_hash = hashlib.sha256(state["agentId"].encode()).hexdigest()[:12]
        claim_contract = {
            "journal": ("openclaw-system", "occ-operator-journal",
                        "openclaw-enterprise-journal-local"),
            "bootstrap": ("openclaw-system", "occ-bootstrap-admin-password",
                          config["storage"]["bootstrapClass"]),
            "gateway": ("openclaw-agents", "gateway-state-" + gateway_hash,
                        config["storage"]["agentClass"]),
        }
        claim_uids = {}
        for key, (namespace, name, storage_class) in claim_contract.items():
            ownership = ((state["namespaceId"], state["agentId"])
                         if key == "gateway" else None)
            first = _claim(before, key, namespace, name, storage_class, ownership)
            second = _claim(after, key, namespace, name, storage_class, ownership)
            require(first == second and before["claims"][key] == after["claims"][key] and
                    before["volumes"][key] == after["volumes"][key],
                    "Enterprise claim changed during capture")
            claim_uids[key] = first
        require(claim_uids["journal"] == operator_contract["journalClaimUid"] and
                before["volumes"]["journal"]["metadata"]["uid"] ==
                operator_contract["journalVolumeUid"] and
                claim_uids["bootstrap"] == operator_contract["bootstrapClaimUid"],
                "Enterprise selected operator claim changed")
        for snapshot in (before, after):
            _stopped(snapshot, state)
            require(snapshot.get("journalSha256") == hashlib.sha256(
                (operator_root / "journal/journal.json").read_bytes()).hexdigest(),
                "Enterprise journal changed during capture")
        require(before["agent"] == after["agent"] and
                before["deployment"] == after["deployment"],
                "Enterprise Agent or deployment changed during capture")
        readers = observations["readers"]
        require(isinstance(readers, dict) and set(readers) == {"operator", "tenant"})
        operator_pod, tenant_pod = readers["operator"], readers["tenant"]
        _reader_pod(operator_pod, "openclaw-system",
                    operator_pod.get("metadata", {}).get("uid")
                    if isinstance(operator_pod, dict) and
                    isinstance(operator_pod.get("metadata"), dict) else None,
                    {"journal": "occ-operator-journal",
                     "bootstrap": "occ-bootstrap-admin-password"})
        _reader_pod(tenant_pod, "openclaw-agents",
                    tenant_pod.get("metadata", {}).get("uid")
                    if isinstance(tenant_pod, dict) and
                    isinstance(tenant_pod.get("metadata"), dict) else None,
                    {"gateway": claim_contract["gateway"][1]})
        _pod_list(observations["duringTenantPods"], tenant_pod)
        _reader_manifest(operator_root, operator_files, expected_sha, "openclaw-system",
                         operator_pod["metadata"]["uid"],
                         {"journal": claim_uids["journal"],
                          "bootstrap": claim_uids["bootstrap"]}, "operator")
        _reader_manifest(tenant_root, tenant_files, expected_sha, "openclaw-agents",
                         tenant_pod["metadata"]["uid"],
                         {"gateway": claim_uids["gateway"]}, "tenant")
        system_before = _secret_list(before.get("systemSecrets"), "openclaw-system")
        system_after = _secret_list(after.get("systemSecrets"), "openclaw-system")
        tenant_before = _secret_list(before.get("tenantSecrets"), "openclaw-agents")
        tenant_after = _secret_list(after.get("tenantSecrets"), "openclaw-agents")
        require(system_before == system_after and tenant_before == tenant_after,
                "Enterprise Secret set changed during capture")
        require(set(SYSTEM_KEYS) <= set(system_before))
        for (name, key), path in CONTROL_OUTPUT.items():
            _write_bytes(material, path, _secret_value(system_before[name], key))
        for name in sorted(SYSTEM_KEYS):
            _write_bytes(material, "system/secrets/" + name + ".json",
                         canonical(system_before[name]))
        model_name = ("secret-" + hashlib.sha256(state["namespaceId"].encode()).hexdigest()[:12] +
                      "-" + hashlib.sha256(state["secretId"].encode()).hexdigest()[:12])
        model_matches = [name for name in tenant_before if name.startswith(model_name + "-")]
        require(len(model_matches) == 1 and
                re.fullmatch(re.escape(model_name) + r"-[0-9a-f]{12}", model_matches[0]))
        expected_tenant = {"occ-model-api-key": ("api-key",),
                           "openclaw-agent-transport-" + gateway_hash: ("app-server-token",),
                           "gateway-password-" + gateway_hash: ("gateway-password",),
                           model_matches[0]: ("value",)}
        require(set(expected_tenant) <= set(tenant_before))
        for name, keys in expected_tenant.items():
            require(set(tenant_before[name]["data"]) == set(keys))
        model = tenant_before[model_matches[0]]
        labels = model["metadata"].get("labels", {})
        annotations = model["metadata"].get("annotations", {})
        require(model.get("type") == "Opaque" and model.get("immutable") is not True and
                labels.get("app.kubernetes.io/managed-by") == "openclaw-enterprise" and
                labels.get("openclaw.dev/namespace") == state["namespaceId"] and
                labels.get("openclaw.dev/secret") == state["secretId"] and
                annotations.get("openclaw.dev/namespace-id") == state["namespaceId"] and
                annotations.get("openclaw.dev/secret-id") == state["secretId"] and
                annotations.get("openclaw.dev/secret-driver-id") == "secret-kubernetes")
        for name, item in tenant_before.items():
            if name not in expected_tenant:
                labels = item["metadata"].get("labels", {})
                annotations = item["metadata"].get("annotations", {})
                require(not name.startswith(("secret-", "gateway-password-",
                                             "openclaw-agent-transport-", "harness-secrets-")) and
                        labels.get("app.kubernetes.io/managed-by") != "openclaw-enterprise" and
                        not any(key.startswith("openclaw.dev/") for key in
                                (*labels, *annotations)),
                        "Enterprise tenant Secret inventory is ambiguous")
        try:
            require(isinstance(json.loads((operator_root / "bootstrap/output.json").read_bytes()),
                               dict) and
                    isinstance(json.loads((operator_root /
                                           "bootstrap/initial-admin-service-key.json").read_bytes()),
                               dict))
        except (ValueError, UnicodeError):
            raise Blocked("Enterprise bootstrap output is invalid") from None
        for name in ("journal", "bootstrap"):
            _move_tree(material, name, operator_root / name)
        for name, item in sorted(tenant_before.items()):
            if name in expected_tenant:
                _write_bytes(material, "tenant/secrets/" + name + ".json", canonical(item))
        _write_bytes(material, "tenant/metadata.json", canonical({
            "namespaceId": state["namespaceId"], "agentId": state["agentId"],
            "modelSecretId": state["secretId"], "gatewayClaim": before["claims"]["gateway"]}))
        _write_bytes(material, "agent/identity.json", canonical({
            "installationId": state["installationId"], "namespaceId": state["namespaceId"],
            "agentId": state["agentId"], "revisionId": state["revisionId"],
            "gatewayClaimUid": claim_uids["gateway"], "agent": before["agent"]}))
        _move_tree(material, "agent/state", tenant_root / "state")
        marker = {"schemaVersion": 2, "sourceSha": expected_sha,
                  "enterpriseSourceSha": config["source"]["revision"],
                  "installationId": state["installationId"],
                  "namespaceId": state["namespaceId"], "agentId": state["agentId"],
                  "revisionId": state["revisionId"],
                  "operatorJournalClaimUid": claim_uids["journal"],
                  "bootstrapClaimUid": claim_uids["bootstrap"],
                  "agentStateClaimUid": claim_uids["gateway"],
                  "operatorJournalVolumeUid": before["volumes"]["journal"]["metadata"]["uid"],
                  "bootstrapVolumeUid": before["volumes"]["bootstrap"]["metadata"]["uid"],
                  "agentStateVolumeUid": before["volumes"]["gateway"]["metadata"]["uid"],
                  "claimUid": claim_uids["gateway"], "writerStopped": True,
                  "continuousFenceVerified": False,
                  "operatorReaderPodUid": operator_pod["metadata"]["uid"],
                  "tenantReaderPodUid": tenant_pod["metadata"]["uid"],
                  "observationSha256": hashlib.sha256(canonical(observations)).hexdigest()}
        _write_bytes(material, "recovery.json", canonical(marker))
        require(not output.exists() and not output.is_symlink())
        os.replace(material, output)
        return marker
    finally:
        shutil.rmtree(scratch)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--operator-archive", required=True, type=Path)
    parser.add_argument("--tenant-archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        assemble(config, args.expected_sha, read_json(args.observations),
                 args.operator_archive, args.tenant_archive, args.output)
    except (Blocked, OCE.Blocked, OSError, ValueError, KeyError, TypeError):
        print("Enterprise private capture assembly blocked", file=sys.stderr)
        return 1
    print("Enterprise private recovery tree staged; continuous fence remains unverified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
