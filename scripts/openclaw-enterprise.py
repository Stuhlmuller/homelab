#!/usr/bin/env python3
"""Fail-closed OpenClaw Enterprise reconciliation entrypoint.

The pinned API does not expose the selected Installation Drivers. Until a
repository-owned proof path exists, commands stop before any mutation. The
recovery and journal helpers below specify the offline retry boundary; they do
not turn incomplete installation evidence into permission to deploy.
"""

import argparse
import base64
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
JOURNAL_FIELDS = frozenset({
    "installationId", "namespaceId", "secretId", "configurationId",
    "configurationGeneration", "agentId", "servicePrincipalId", "roleId",
    "bindingId", "revisionId", "desiredHash", "pending",
})
ID_PREFIXES = {
    "installationId": "ins_", "namespaceId": "ns_", "secretId": "sec_",
    "configurationId": "cfg_", "agentId": "agt_", "revisionId": "rev_",
}


class Blocked(RuntimeError):
    """An unknown, unauthorized or ambiguous state that must not be retried."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise Blocked("Enterprise API redirected; refusing to forward its credential")


class API:
    """Exact-origin API reader. Mutations remain fenced by the Driver gap."""

    def __init__(self, origin, key):
        parsed = urlsplit(origin)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/"):
            raise Blocked("Enterprise API origin must be an HTTPS origin")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise Blocked("Enterprise API origin contains unsupported components")
        if not isinstance(key, str) or not key.strip() or "\r" in key or "\n" in key:
            raise Blocked("Enterprise service key is invalid")
        self.origin = origin.rstrip("/")
        self.key = key
        self.opener = build_opener(NoRedirect())

    def get(self, path):
        if not path.startswith("/") or "?" in path or "#" in path:
            raise Blocked("Enterprise API path is not exact")
        request = Request(self.origin + path, headers={"x-api-key": self.key}, method="GET")
        try:
            with self.opener.open(request, timeout=15) as response:
                if response.status != 200:
                    raise Blocked(f"Enterprise API read returned HTTP {response.status}")
                payload = json.load(response)
        except HTTPError as error:
            raise Blocked(f"Enterprise API read returned HTTP {error.code}") from None
        except (URLError, TimeoutError, ValueError, json.JSONDecodeError):
            raise Blocked("Enterprise API read failed or returned invalid JSON") from None
        if not isinstance(payload, dict) or "data" not in payload:
            raise Blocked("Enterprise API response has no data envelope")
        return payload["data"]


def require_driver_identity(installation):
    """GET /installation is deliberately insufficient at the pinned revision."""
    if not isinstance(installation, dict) or not isinstance(installation.get("id"), str):
        raise Blocked("Enterprise Installation response is invalid")
    raise Blocked("GET /installation cannot prove selected Drivers; activation is blocked")


def check(config, api):
    _validate_config(config)
    installation = api.get("/installation")
    require_driver_identity(installation)


def reconcile(config, api, expected_sha):
    _validate_config(config)
    if not SHA.fullmatch(expected_sha):
        raise Blocked("Expected repository SHA is invalid")
    # No journal or API mutation is started before the selected Driver proof.
    installation = api.get("/installation")
    require_driver_identity(installation)


def verify(config, api):
    # Verification is a read, never an inference probe or implicit deployment.
    return check(config, api)


def _validate_config(config):
    if not isinstance(config, dict) or config.get("schemaVersion") != 1:
        raise Blocked("Enterprise configuration schema is invalid")
    if type(config.get("activationEnabled")) is not bool:
        raise Blocked("Enterprise activation switch is invalid")
    source = config.get("source")
    if not isinstance(source, dict):
        raise Blocked("Enterprise source definition is invalid")
    if source.get("repository") != "https://github.com/openclaw/openclaw-enterprise":
        raise Blocked("Enterprise source repository changed")
    if source.get("revision") != "33bb74590a749f37934da4502fca6035cd234a55":
        raise Blocked("Enterprise source revision changed")
    namespace = config.get("namespace")
    if not isinstance(namespace, dict):
        raise Blocked("Enterprise Namespace definition is invalid")
    if namespace.get("logicalName") != "claw" or namespace.get("existingNamespace") != "openclaw-agents":
        raise Blocked("Enterprise Namespace identity changed")
    agent = config.get("agent")
    if not isinstance(agent, dict):
        raise Blocked("Enterprise agent definition is invalid")
    if (agent.get("name") != "claw" or agent.get("type") != "embedded" or
            agent.get("channels") != [] or agent.get("backend") is not None or
            agent.get("sandbox") is not None):
        raise Blocked("Enterprise agent is not the approved fresh Embedded shape")
    if config["activationEnabled"]:
        model = config.get("model", {})
        secrets = config.get("secrets", {})
        if (not isinstance(model, dict) or not isinstance(model.get("provider"), str) or
                not model["provider"] or not isinstance(model.get("id"), str) or
                not model["id"] or not isinstance(secrets, dict) or
                secrets.get("modelApiKey") != "/homelab/openclaw-enterprise/model-api-key"):
            raise Blocked("activation requires explicit model and dedicated key reference")


def _require(condition, reason):
    if not condition:
        raise Blocked(reason)


def _created_at(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _require(parsed.tzinfo is not None, "Installation snapshot lacks timestamps")
        return parsed
    except (AttributeError, TypeError, ValueError):
        raise Blocked("Installation snapshot lacks timestamps") from None


def _controller_owner(metadata, kind, uid, name):
    owners = [item for item in metadata.get("ownerReferences", [])
              if item.get("controller") is True]
    _require(len(owners) == 1 and owners[0].get("kind") == kind and
             owners[0].get("uid") == uid and owners[0].get("name") == name,
             "Installation Pod ownership is foreign")


def _startup_mount(spec, component, secret_name, image):
    volumes = [item for item in spec.get("volumes", [])
               if item.get("name") == "installation-startup"]
    projected = volumes[0].get("secret", {}) if len(volumes) == 1 else {}
    _require(len(volumes) == 1 and projected.get("secretName") == secret_name and
             projected.get("items") == [{"key": "installation.yaml", "path": "installation.yaml"}] and
             projected.get("defaultMode", 420) == 420 and projected.get("optional") in (None, False),
             "Installation Secret projection changed")
    containers = [item for item in spec.get("containers", []) if item.get("name") == component]
    _require(len(containers) == 1 and not any(
        item.get("name") == component for item in spec.get("initContainers", [])),
        "Installation controller placement changed")
    container = containers[0]
    _require(container.get("image") == image, "Installation controller image changed")
    env = [item for item in container.get("env", []) if item.get("name") == "OCC_CONFIG_PATH"]
    _require(len(env) == 1 and env[0].get("value") ==
             "/etc/openclaw/installation/installation.yaml" and
             "valueFrom" not in env[0],
             "Installation startup path changed")
    mounts = container.get("volumeMounts", [])
    selected = [item for item in mounts if item.get("name") == "installation-startup"]
    _require(len(selected) == 1 and
             selected[0].get("mountPath") == "/etc/openclaw/installation" and
             selected[0].get("readOnly") is True and
             not selected[0].get("subPath") and not selected[0].get("subPathExpr"),
             "Installation startup mount changed")
    _require(not any(item.get("name") != "installation-startup" and
                     (item.get("mountPath") == "/etc/openclaw/installation" or
                      "/etc/openclaw/installation".startswith(
                          str(item.get("mountPath", "")) + "/") or
                      str(item.get("mountPath", "")).startswith(
                          "/etc/openclaw/installation/"))
                     for item in mounts), "Installation startup file is shadowed")


def _attest_installation_snapshot(candidate, digest, installation_id, snapshot, image):
    _require(isinstance(candidate, bytes) and 0 < len(candidate) <= 1048576 and
             isinstance(digest, str) and HEX64.fullmatch(digest) and
             hashlib.sha256(candidate).hexdigest() == digest,
             "reviewed Installation bytes or checksum changed")
    _require(isinstance(installation_id, str) and installation_id.startswith("ins_") and
             isinstance(snapshot, dict), "Installation identity evidence is invalid")
    secret = snapshot["secret"]
    metadata = secret["metadata"]
    secret_name = "occ-installation-startup-" + digest[:32]
    _require(metadata.get("name") == secret_name and
             metadata.get("namespace") == "openclaw-system" and
             isinstance(metadata.get("uid"), str) and bool(metadata["uid"]) and
             isinstance(metadata.get("resourceVersion"), str) and bool(metadata["resourceVersion"]) and
             metadata.get("annotations", {}).get("openclaw.dev/installation-id") == installation_id and
             secret.get("immutable") is True and secret.get("type") == "Opaque" and
             set(secret.get("data", {})) == {"installation.yaml"},
             "Installation Secret is mutable or foreign")
    try:
        decoded = base64.b64decode(secret["data"]["installation.yaml"], validate=True)
    except (ValueError, TypeError, base64.binascii.Error):
        raise Blocked("Installation Secret data is invalid") from None
    _require(decoded == candidate, "Installation Secret differs from reviewed candidate")
    secret_time = _created_at(metadata.get("creationTimestamp"))
    receipt = {"installationId": installation_id, "installationChecksum": digest,
               "secretUid": metadata["uid"],
               "secretResourceVersion": metadata["resourceVersion"],
               "deploymentUids": {}, "replicaSetUids": {}, "podUids": {}}
    for component in ("api", "worker"):
        name = "openclaw-enterprise-" + component
        labels = {"app.kubernetes.io/instance": "oce",
                  "app.kubernetes.io/component": component}
        deployment = snapshot["deployments"][component]
        dep_meta = deployment["metadata"]
        dep_status = deployment["status"]
        generation = dep_meta.get("generation")
        _require(dep_meta.get("name") == name and dep_meta.get("namespace") == "openclaw-system" and
                 isinstance(dep_meta.get("uid"), str) and bool(dep_meta["uid"]) and
                 all(dep_meta.get("labels", {}).get(key) == value for key, value in labels.items()) and
                 type(generation) is int and generation > 0 and
                 deployment["spec"].get("replicas") == 1 and
                 dep_status.get("observedGeneration", 0) >= generation and
                 all(dep_status.get(field) == 1 for field in
                     ("replicas", "updatedReplicas", "availableReplicas")),
                 "Installation Deployment identity or readiness changed")
        template = deployment["spec"]["template"]
        _require(template.get("metadata", {}).get("annotations", {}).get(
            "openclaw.dev/installation-checksum") == digest,
            "Installation Deployment checksum changed")
        _startup_mount(template["spec"], component, secret_name, image)
        replicasets = snapshot["replicaSets"][component]
        pods = snapshot["pods"][component]
        _require(len(replicasets) == 1 and len(pods) == 1,
                 "Installation workload has ambiguous replicas")
        rs, pod = replicasets[0], pods[0]
        rs_meta, pod_meta = rs["metadata"], pod["metadata"]
        _controller_owner(rs_meta, "Deployment", dep_meta["uid"], name)
        _require(rs["spec"]["template"]["metadata"]["annotations"].get(
            "openclaw.dev/installation-checksum") == digest,
            "Installation ReplicaSet checksum changed")
        _startup_mount(rs["spec"]["template"]["spec"], component, secret_name, image)
        _controller_owner(pod_meta, "ReplicaSet", rs_meta.get("uid"), rs_meta.get("name"))
        _require(pod_meta.get("namespace") == "openclaw-system" and
                 not pod_meta.get("deletionTimestamp") and
                 all(pod_meta.get("labels", {}).get(key) == value for key, value in labels.items()) and
                 pod_meta.get("annotations", {}).get("openclaw.dev/installation-checksum") == digest and
                 _created_at(pod_meta.get("creationTimestamp")) > secret_time,
                 "Installation Pod predates its immutable Secret or is foreign")
        _startup_mount(pod["spec"], component, secret_name, image)
        status = pod["status"]
        container_statuses = [item for item in status.get("containerStatuses", [])
                              if item.get("name") == component]
        _require(status.get("phase") == "Running" and
                 any(item.get("type") == "Ready" and item.get("status") == "True"
                     for item in status.get("conditions", [])) and
                 len(container_statuses) == 1 and container_statuses[0].get("ready") is True and
                 isinstance(container_statuses[0].get("state", {}).get("running"), dict),
                 "Installation Pod is not ready")
        _require(_created_at(container_statuses[0]["state"]["running"].get("startedAt")) > secret_time,
                 "Installation controller predates its immutable Secret")
        receipt["deploymentUids"][component] = dep_meta["uid"]
        receipt["replicaSetUids"][component] = rs_meta["uid"]
        receipt["podUids"][component] = pod_meta["uid"]
    return receipt


def attest_stable_installation(candidate, digest, installation_id, before, after, image):
    """Compare reviewed bytes with two read-only workload snapshots around API GET."""
    try:
        first = _attest_installation_snapshot(candidate, digest, installation_id, before, image)
        second = _attest_installation_snapshot(candidate, digest, installation_id, after, image)
    except (AttributeError, KeyError, TypeError, IndexError):
        raise Blocked("Installation workload evidence is incomplete") from None
    _require(first == second, "Installation workload changed during proof")
    return second


def discover_exact(items, name, journal_id, expected=None):
    """Refuse duplicate names and unjournaled or changed server identities."""
    if not isinstance(items, list):
        raise Blocked("Enterprise list response is invalid")
    matches = [item for item in items if isinstance(item, dict) and item.get("name") == name]
    if len(matches) > 1:
        raise Blocked("duplicate Enterprise logical identity")
    if not matches:
        if journal_id is not None:
            raise Blocked("journaled Enterprise identity disappeared")
        return None
    item = matches[0]
    if journal_id is None:
        raise Blocked("unjournaled Enterprise identity may be foreign")
    if item.get("id") != journal_id:
        raise Blocked("changed identity for Enterprise resource")
    for field, value in (expected or {}).items():
        if item.get(field) != value:
            raise Blocked("changed identity for Enterprise resource")
    return item


def configuration_configmap_name(configuration_id):
    """Pinned KubernetesConfigurationDriver.kubernetesConfigurationName."""
    if not isinstance(configuration_id, str) or not configuration_id.startswith("cfg_"):
        raise Blocked("Configuration ID is invalid")
    slug = re.sub(r"[^a-z0-9-]+", "-", configuration_id[4:].lower()).strip("-")[:46].rstrip("-")
    return f"cfg-{slug or 'config'}-{hashlib.sha256(configuration_id.encode()).hexdigest()[:12]}"


def recover_configuration(candidates, exact, tenant_namespace):
    """Adopt only one exact owned ConfigMap confirmed by exact API GET.

    `candidates` must come from a protected read-only ConfigMap/audit lookup;
    this function never lists tenant ConfigMaps with the OCE API credential.
    """
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise Blocked("ambiguous Configuration create outcome")
    if not isinstance(exact, dict):
        raise Blocked("Configuration API read is missing")
    candidate = candidates[0]
    metadata = candidate.get("metadata", {}) if isinstance(candidate, dict) else {}
    labels = metadata.get("labels", {})
    annotations = metadata.get("annotations", {})
    configuration_id = exact.get("id")
    namespace_id = exact.get("namespaceId")
    expected_labels = {
        "app.kubernetes.io/managed-by": "openclaw-enterprise",
        "openclaw.dev/namespace": namespace_id,
        "openclaw.dev/configuration": configuration_id,
    }
    expected_annotations = {
        "openclaw.dev/namespace-id": namespace_id,
        "openclaw.dev/configuration-id": configuration_id,
        "openclaw.dev/configuration-kind": "agent",
        "openclaw.dev/configuration-generation": str(exact.get("generation")),
    }
    if (not isinstance(configuration_id, str) or not isinstance(namespace_id, str) or
            exact.get("kind") != "agent" or
            metadata.get("name") != configuration_configmap_name(configuration_id) or
            metadata.get("namespace") != tenant_namespace or
            any(labels.get(key) != value for key, value in expected_labels.items()) or
            any(annotations.get(key) != value for key, value in expected_annotations.items()) or
            annotations.get("openclaw.dev/configuration-created-at") != exact.get("createdAt")):
        raise Blocked("foreign Configuration recovery candidate")
    try:
        values = json.loads(candidate["data"]["openclaw.json"])
    except (KeyError, TypeError, ValueError):
        raise Blocked("Configuration recovery document is invalid") from None
    if not isinstance(values, dict) or values != exact.get("values"):
        raise Blocked("Configuration recovery document does not match API GET")
    return configuration_id


def configuration_patch(current, desired_values, journal_generation):
    if (not isinstance(current, dict) or current.get("generation") != journal_generation or
            not isinstance(journal_generation, int) or journal_generation < 1):
        raise Blocked("Configuration generation changed; do not silently rebase")
    if not isinstance(desired_values, dict):
        raise Blocked("Desired Configuration values are invalid")
    if current.get("values") == desired_values:
        return None
    return {"values": desired_values, "expectedGeneration": journal_generation}


def recover_revision(revisions, baseline_ids, agent_id, configuration_id, generation):
    if not isinstance(revisions, list) or not isinstance(baseline_ids, set):
        raise Blocked("Revision recovery evidence is invalid")
    new = [item for item in revisions if isinstance(item, dict) and item.get("id") not in baseline_ids]
    if not new:
        raise Blocked("deploy outcome remains unknown; do not retry")
    matching = [item for item in new if item.get("agentId") == agent_id and
                item.get("configurationId") == configuration_id and
                item.get("configurationGeneration") == generation]
    if len(new) != 1 or len(matching) != 1:
        raise Blocked("ambiguous deploy outcome; do not retry")
    return matching[0]["id"]


def should_deploy(agent, revision, deployment, configuration_id, generation):
    """Decide from one completed active revision; unknown outcomes never retry."""
    if (not isinstance(agent, dict) or not isinstance(revision, dict) or
            not isinstance(deployment, dict) or not isinstance(generation, int) or
            generation < 1):
        raise Blocked("deployment evidence is incomplete")
    if (agent.get("status") != "active" or agent.get("desiredRuntimeState") != "running" or
            agent.get("configurationId") != configuration_id or
            revision.get("agentId") != agent.get("id") or
            revision.get("configurationId") != configuration_id or
            agent.get("activeRevisionId") != revision.get("id") or
            deployment.get("deploymentId") != revision.get("id") or
            deployment.get("agentId") != agent.get("id") or
            deployment.get("namespaceId") != agent.get("namespaceId")):
        raise Blocked("active deployment identity changed")
    if deployment.get("status") in ("queued", "running"):
        raise Blocked("deployment is in progress")
    if deployment.get("status") == "failed":
        raise Blocked("deployment failed")
    if deployment.get("status") != "succeeded":
        raise Blocked("deployment state is unknown")
    active_generation = revision.get("configurationGeneration")
    if not isinstance(active_generation, int) or active_generation < 1 or generation < active_generation:
        raise Blocked("active Configuration generation is invalid")
    return generation > active_generation


def exact_model_grant(roles, bindings, namespace_id, principal_id, secret_id):
    """A selected Agent must hold one exact Secret-operate binding."""
    permission = [{"action": "operate", "resourceKind": "secret"}]
    exact_roles = [role for role in roles if role.get("namespaceId") == namespace_id and
                   role.get("permissions") == permission]
    if len(exact_roles) != 1:
        raise Blocked("exact model Secret grant role is absent or ambiguous")
    role_id = exact_roles[0]["id"]
    exact_bindings = [binding for binding in bindings if
                      binding.get("namespaceId") == namespace_id and
                      binding.get("subjectKind") == "identity" and
                      binding.get("subjectId") == principal_id and
                      binding.get("roleId") == role_id and
                      binding.get("resourceKind") == "secret" and
                      binding.get("resourceId") == secret_id]
    if len(exact_bindings) != 1:
        raise Blocked("exact model Secret grant is absent or ambiguous")
    return role_id, exact_bindings[0]["id"]


class ProtectedJournal:
    """Serialized, source-bound, credential-free state on a private durable mount."""

    def __init__(self, path, source_sha, config_sha):
        self.path = Path(path)
        self.source_sha = source_sha
        self.config_sha = config_sha
        self.lock_fd = None
        self.state = {}

    def __enter__(self):
        if not self.path.is_absolute() or not SHA.fullmatch(self.source_sha) or not HEX64.fullmatch(self.config_sha):
            raise Blocked("Journal identity is invalid")
        parent = self.path.parent
        if parent.resolve() != parent or not parent.is_dir():
            raise Blocked("Journal parent must be a real private directory")
        parent_stat = parent.stat()
        if parent_stat.st_uid != os.getuid() or stat.S_IMODE(parent_stat.st_mode) != 0o700:
            raise Blocked("Journal parent owner or mode is unsafe")
        lock_path = self.path.with_name(self.path.name + ".lock")
        self._check_file(lock_path)
        self.lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._check_file(self.path)
            if self.path.exists():
                raw = self.path.read_bytes()
                if len(raw) > 65536:
                    raise Blocked("Journal is oversized")
                document = json.loads(raw)
                if (not isinstance(document, dict) or document.get("schemaVersion") != 1 or
                        document.get("sourceSha") != self.source_sha or
                        document.get("configSha") != self.config_sha):
                    raise Blocked("Journal source or desired input changed")
                self.state = document.get("state", {})
                self._validate_state(self.state)
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, _type, _value, _traceback):
        if self.lock_fd is not None:
            fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
            os.close(self.lock_fd)
            self.lock_fd = None

    @staticmethod
    def _check_file(path):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode):
            raise Blocked("Journal path is a symlink")
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise Blocked("Journal file type or mode is unsafe")
        if info.st_uid != os.getuid():
            raise Blocked("Journal file owner is unsafe")

    @staticmethod
    def _validate_state(state):
        if not isinstance(state, dict) or not set(state).issubset(JOURNAL_FIELDS):
            raise Blocked("Journal contains unexpected fields")
        for field, value in state.items():
            if field == "pending":
                continue
            if field == "configurationGeneration":
                if type(value) is not int or not 1 <= value <= 9007199254740991:
                    raise Blocked("Journal Configuration generation is invalid")
            elif field == "desiredHash":
                if not isinstance(value, str) or not HEX64.fullmatch(value):
                    raise Blocked("Journal desired hash is invalid")
            elif (not isinstance(value, str) or not 1 <= len(value) <= 200 or
                  not re.fullmatch(r"[A-Za-z0-9._~:@/-]+", value) or
                  (field in ID_PREFIXES and not value.startswith(ID_PREFIXES[field]))):
                raise Blocked("Journal resource identity is invalid")
        pending = state.get("pending")
        if pending is not None:
            if (not isinstance(pending, dict) or
                    set(pending) - {"operation", "baselineRevisionIds"} or
                    pending.get("operation") not in ("configuration-create", "deploy") or
                    not isinstance(pending.get("baselineRevisionIds", []), list) or
                    any(not isinstance(item, str) or not item.startswith("rev_") or
                        not re.fullmatch(r"[A-Za-z0-9._~:@/-]{1,200}", item)
                        for item in pending.get("baselineRevisionIds", []))):
                raise Blocked("Journal pending operation is invalid")

    def save(self, state):
        self._validate_state(state)
        document = {"schemaVersion": 1, "sourceSha": self.source_sha,
                    "configSha": self.config_sha, "state": state}
        encoded = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
        if len(encoded) > 65536:
            raise Blocked("Journal is oversized")
        fd, temporary = tempfile.mkstemp(prefix=".journal-", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.state = dict(state)


def _read_key(path):
    candidate = Path(path)
    ProtectedJournal._check_file(candidate)
    if not candidate.is_absolute() or not candidate.is_file():
        raise Blocked("Enterprise credential file is missing")
    try:
        payload = json.loads(candidate.read_text())
        key = payload["data"]["key"]
    except (OSError, ValueError, KeyError, TypeError):
        raise Blocked("Enterprise credential file is invalid") from None
    if not isinstance(key, str) or not key.strip() or "\r" in key or "\n" in key:
        raise Blocked("Enterprise credential file contains an invalid key")
    return key


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "reconcile", "verify"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--expected-sha")
    parser.add_argument("--credential-file", type=Path)
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text())
        _validate_config(config)
        if args.command == "reconcile":
            if args.expected_sha is None or args.credential_file is None:
                raise Blocked("reconcile requires expected SHA and mounted credential file")
            actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
            if actual != args.expected_sha:
                raise Blocked("reconcile source SHA is not exact")
            key_path = args.credential_file
        else:
            key_path = Path(config["bootstrap"]["serviceKeyFile"])
        api = API(config["privateOrigins"]["console"], _read_key(key_path))
        if args.command == "reconcile":
            reconcile(config, api, args.expected_sha)
        elif args.command == "verify":
            verify(config, api)
        else:
            check(config, api)
    except (Blocked, OSError, ValueError, KeyError) as error:
        print(f"OpenClaw Enterprise {args.command} blocked: {error}", file=sys.stderr)
        return 1
    print(f"OpenClaw Enterprise {args.command} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
