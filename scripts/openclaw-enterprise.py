#!/usr/bin/env python3
"""Fail-closed OpenClaw Enterprise reconciliation entrypoint.

Read-only checks attest the reviewed startup file and current controller Pods.
Reconciliation creates only reviewed Namespace, Configuration and stopped Agent
state while activation is disabled.
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
CONSOLE_ORIGIN = "https://console.oce.stinkyboi.com"
KUBE_SERVER = "https://kubernetes-api-ci.stinkyboi.com"
INSTALLATION_APP = ROOT / "clusters/homelab/apps/openclaw-enterprise"
APPROVED_MODEL = {
    "provider": "openai",
    "id": "openrouter/free",
    "baseUrl": "https://openrouter.ai/api/v1",
    "api": "openai-completions",
}
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

# Pinned chart rbac.yaml at source revision 33bb745; repositoryCredentials=false,
# agentRuntimeLogs=true in the reviewed Helm values.
TENANT_ROLE_RULES = {
    "oce-openclaw-tenant-worker": [
        ("", ("secrets",), ("get", "create", "update", "delete")),
        ("", ("configmaps", "serviceaccounts", "services", "resourcequotas", "limitranges"),
         ("get", "list", "create", "patch", "delete")),
        ("", ("pods",), ("get", "list", "watch", "patch")),
        ("", ("pods/proxy",), ("get",)),
        ("", ("persistentvolumeclaims",), ("get", "create", "patch", "delete")),
        ("apps", ("deployments",), ("get", "list", "create", "patch", "delete")),
        ("batch", ("jobs",), ("get", "create", "delete")),
        ("networking.k8s.io", ("networkpolicies",),
         ("get", "list", "create", "patch", "delete")),
        ("gateway.networking.k8s.io", ("httproutes",),
         ("get", "create", "patch", "delete")),
        ("gateway.envoyproxy.io", ("securitypolicies",),
         ("get", "create", "patch", "delete")),
        ("discovery.k8s.io", ("endpointslices",), ("get", "list")),
    ],
    "oce-openclaw-tenant-api": [
        ("", ("secrets",), ("get", "create", "update", "patch", "delete")),
        ("apps", ("deployments",), ("list",)),
        ("", ("pods",), ("get", "list")),
        ("", ("pods/proxy",), ("get",)),
        ("", ("pods/log",), ("get",)),
        ("", ("events",), ("get", "list")),
    ],
    "oce-openclaw-tenant-configuration": [
        ("", ("configmaps",), ("get", "list", "create", "update", "patch", "delete")),
    ],
}

# Exact base policies emitted by the pinned Kubernetes Compute Driver for the
# reviewed single-cluster Installation. Agent-specific policies may be added.
REQUIRED_TENANT_POLICY_SPECS = {
    "default-deny": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
    "allow-dns": {
        "podSelector": {"matchLabels": {"openclaw.dev/network-profile": "broad-egress-v1"}},
        "policyTypes": ["Egress"],
        "egress": [{
            "to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name":
                                                         "kube-system"}},
                    "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}],
            "ports": [{"protocol": protocol, "port": port}
                      for port in (53, 5353) for protocol in ("UDP", "TCP")],
        }],
    },
    "allow-gateway-ingress": {
        "podSelector": {"matchLabels": {"openclaw.dev/workload-role": "gateway",
                                         "openclaw.dev/network-profile": "broad-egress-v1"}},
        "policyTypes": ["Ingress"],
        "ingress": [{
            "from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name":
                                                           "envoy-gateway-system"}},
                      "podSelector": {"matchLabels": {
                          "gateway.envoyproxy.io/owning-gateway-namespace": "openclaw-system",
                          "gateway.envoyproxy.io/owning-gateway-name": "oce-private-gateway"}}}],
            "ports": [{"protocol": "TCP", "port": 8080}],
        }],
    },
}


def _normalized_policy_spec(spec):
    _require(isinstance(spec, dict) and
             set(spec) <= {"podSelector", "policyTypes", "ingress", "egress"} and
             isinstance(spec.get("podSelector"), dict) and
             isinstance(spec.get("policyTypes"), list) and spec["policyTypes"] and
             all(policy_type in ("Ingress", "Egress") for policy_type in spec["policyTypes"]) and
             all(key not in spec or isinstance(spec[key], list)
                 for key in ("ingress", "egress")),
             "prepared tenant NetworkPolicy spec is invalid")
    return {"podSelector": spec.get("podSelector"),
            "policyTypes": sorted(spec["policyTypes"]),
            "ingress": spec.get("ingress") or [], "egress": spec.get("egress") or []}


def _normalized_role_rules(rules):
    _require(isinstance(rules, list), "prepared tenant ClusterRole rules are invalid")
    normalized = []
    for rule in rules:
        _require(isinstance(rule, dict) and set(rule) == {"apiGroups", "resources", "verbs"} and
                 isinstance(rule.get("apiGroups"), list) and rule["apiGroups"] and
                 all(isinstance(group, str) for group in rule["apiGroups"]) and
                 all(isinstance(rule.get(key), list) and rule[key] and
                     all(isinstance(value, str) and value for value in rule[key])
                     for key in ("resources", "verbs")),
                 "prepared tenant ClusterRole rules are invalid")
        normalized.append((tuple(sorted(rule["apiGroups"])),
                           tuple(sorted(rule["resources"])), tuple(sorted(rule["verbs"]))))
    return sorted(normalized)


class Blocked(RuntimeError):
    """An unknown, unauthorized or ambiguous state that must not be retried."""


class DefinitiveRejection(Blocked):
    """Pinned API rejected authentication or authorization before mutation."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise Blocked("Enterprise API redirected; refusing to forward its credential")


class API:
    """Exact-origin API client that never exposes response bodies on failure."""

    def __init__(self, origin, key):
        if origin != CONSOLE_ORIGIN:
            raise Blocked("Enterprise console origin changed")
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
        return self._request("GET", path, None, 200)

    def post(self, path, body):
        return self._request("POST", path, body, 201)

    def _request(self, method, path, body, expected_status):
        if not path.startswith("/") or "?" in path or "#" in path:
            raise Blocked("Enterprise API path is not exact")
        if method == "POST" and not isinstance(body, dict):
            raise Blocked("Enterprise API mutation body is invalid")
        headers = {"x-api-key": self.key}
        encoded = None
        if body is not None:
            headers["content-type"] = "application/json"
            encoded = json.dumps(body, separators=(",", ":")).encode()
        request = Request(self.origin + path, data=encoded, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=15) as response:
                if response.status != expected_status:
                    raise Blocked(f"Enterprise API returned HTTP {response.status}")
                payload = json.load(response)
        except HTTPError as error:
            if error.code in (401, 403):
                raise DefinitiveRejection(f"Enterprise API returned HTTP {error.code}") from None
            raise Blocked(f"Enterprise API returned HTTP {error.code}") from None
        except (URLError, TimeoutError, ValueError, json.JSONDecodeError):
            raise Blocked("Enterprise API request failed or returned invalid JSON") from None
        if not isinstance(payload, dict) or "data" not in payload:
            raise Blocked("Enterprise API response has no data envelope")
        return payload["data"]


class Kubernetes:
    """Read exact installed controller objects without printing Secret data."""

    @staticmethod
    def _json(*args):
        try:
            result = subprocess.run(["kubectl", "--request-timeout=15s", *args],
                                    capture_output=True, text=True, timeout=20, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise Blocked("Kubernetes proof read is unavailable") from None
        if result.returncode or len(result.stdout) > 4 * 1048576:
            raise Blocked("Kubernetes proof read failed")
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise Blocked("Kubernetes proof returned invalid JSON") from None

    def snapshot(self, digest):
        context = self._json("config", "view", "--minify", "-o=json")
        _require(isinstance(context, dict) and isinstance(context.get("clusters"), list) and
                 len(context["clusters"]) == 1 and
                 isinstance(context["clusters"][0], dict) and
                 isinstance(context["clusters"][0].get("cluster"), dict) and
                 context["clusters"][0].get("cluster", {}).get("server") == KUBE_SERVER,
                 "Kubernetes proof context changed")
        namespace = "openclaw-system"
        labels = "app.kubernetes.io/name=openclaw-enterprise,app.kubernetes.io/instance=oce"
        secret_name = "occ-installation-startup-" + digest[:32]
        snapshot = {"secret": self._json("-n", namespace, "get", "secret", secret_name, "-o=json"),
                    "deployments": {}, "replicaSets": {}, "pods": {}}
        for component in ("api", "worker"):
            name = "openclaw-enterprise-" + component
            selector = labels + ",app.kubernetes.io/component=" + component
            snapshot["deployments"][component] = self._json(
                "-n", namespace, "get", "deployment", name, "-o=json")
            for kind, field in (("replicasets", "replicaSets"), ("pods", "pods")):
                listing = self._json("-n", namespace, "get", kind, "-l", selector, "-o=json")
                _require(isinstance(listing, dict) and isinstance(listing.get("items"), list),
                         "Installation workload list is invalid")
                snapshot[field][component] = listing["items"]
        return snapshot

    def tenant_prepared(self, namespace_id=None, require_claimed=False):
        """Read upstream adoption prerequisites before any Namespace POST/recovery."""
        context = self._json("config", "view", "--minify", "-o=json")
        _require(isinstance(context, dict) and isinstance(context.get("clusters"), list) and
                 len(context["clusters"]) == 1 and
                 isinstance(context["clusters"][0], dict) and
                 isinstance(context["clusters"][0].get("cluster"), dict) and
                 context["clusters"][0].get("cluster", {}).get("server") == KUBE_SERVER,
                 "Kubernetes proof context changed")
        namespace = self._json("get", "namespace", "openclaw-agents", "-o=json")
        _require(isinstance(namespace, dict), "prepared tenant Namespace is invalid")
        metadata = namespace.get("metadata", {})
        _require(isinstance(metadata, dict) and
                 isinstance(metadata.get("annotations"), dict) and
                 isinstance(metadata.get("labels"), dict) and
                 isinstance(namespace.get("status"), dict) and
                 metadata.get("name") == "openclaw-agents" and
                 isinstance(metadata.get("resourceVersion"), str) and
                 bool(metadata["resourceVersion"]) and
                 not metadata.get("deletionTimestamp") and
                 metadata["annotations"].get("openclaw.dev/namespace-lifecycle") == "external" and
                 metadata["labels"].get("pod-security.kubernetes.io/enforce") == "restricted" and
                 metadata["labels"].get("pod-security.kubernetes.io/audit") == "restricted" and
                 metadata["labels"].get("pod-security.kubernetes.io/warn") == "restricted" and
                 namespace.get("status", {}).get("phase") == "Active",
                 "prepared tenant Namespace is absent or changed")
        markers = (metadata["labels"].get("openclaw.dev/namespace"),
                   metadata["annotations"].get("openclaw.dev/namespace-id"),
                   metadata["labels"].get("openclaw.dev/gateway-namespace"))
        if namespace_id is None:
            _require(all(marker is None for marker in markers),
                     "prepared tenant Namespace has foreign ownership markers")
        else:
            _require(all(marker is None or marker == namespace_id for marker in markers),
                     "prepared tenant Namespace has foreign ownership markers")
            if require_claimed:
                _require(all(marker == namespace_id for marker in markers),
                         "prepared tenant Namespace has not been claimed")
        policies = self._json("-n", "openclaw-agents", "get", "networkpolicies", "-o=json")
        _require(isinstance(policies, dict) and isinstance(policies.get("items"), list),
                 "prepared tenant NetworkPolicy list is invalid")
        observed_policies = {}
        for policy in policies["items"]:
            _require(namespace_id is not None and isinstance(policy, dict) and
                     policy.get("kind") in (None, "NetworkPolicy") and
                     isinstance(policy.get("metadata"), dict) and
                     isinstance(policy["metadata"].get("name"), str) and
                     bool(policy["metadata"]["name"]) and
                     policy["metadata"].get("namespace") == "openclaw-agents" and
                     isinstance(policy["metadata"].get("labels"), dict) and
                     isinstance(policy["metadata"].get("annotations"), dict) and
                     policy["metadata"]["labels"].get("app.kubernetes.io/managed-by") ==
                     "openclaw-enterprise" and
                     policy["metadata"]["labels"].get("openclaw.dev/namespace") == namespace_id and
                     policy["metadata"]["annotations"].get("openclaw.dev/namespace-id") == namespace_id,
                     "prepared tenant has a foreign NetworkPolicy")
            policy_name = policy["metadata"]["name"]
            _require(policy_name not in observed_policies,
                     "prepared tenant NetworkPolicy list is ambiguous")
            observed_policies[policy_name] = policy
        if require_claimed:
            _require(set(observed_policies) == set(REQUIRED_TENANT_POLICY_SPECS),
                     "prepared tenant NetworkPolicy set is absent or changed")
            for policy_name, expected_spec in REQUIRED_TENANT_POLICY_SPECS.items():
                observed = observed_policies.get(policy_name)
                _require(observed is not None and
                         _normalized_policy_spec(observed.get("spec")) ==
                         _normalized_policy_spec(expected_spec),
                         "prepared tenant NetworkPolicy is absent or changed")
        for name, role, subject in (
            ("openclaw-enterprise-worker", "oce-openclaw-tenant-worker", "openclaw-enterprise-worker"),
            ("openclaw-enterprise-api-secrets", "oce-openclaw-tenant-api", "openclaw-enterprise-api"),
            ("openclaw-enterprise-api-configuration", "oce-openclaw-tenant-configuration", "openclaw-enterprise-api"),
        ):
            cluster_role = self._json("get", "clusterrole", role, "-o=json")
            _require(isinstance(cluster_role, dict) and
                     isinstance(cluster_role.get("metadata"), dict) and
                     cluster_role["metadata"].get("name") == role and
                     cluster_role.get("aggregationRule") is None and
                     _normalized_role_rules(cluster_role.get("rules")) ==
                     _normalized_role_rules([
                         {"apiGroups": [group], "resources": list(resources), "verbs": list(verbs)}
                         for group, resources, verbs in TENANT_ROLE_RULES[role]
                     ]),
                     "prepared tenant ClusterRole is absent or changed")
            binding = self._json("-n", "openclaw-agents", "get", "rolebinding", name, "-o=json")
            _require(isinstance(binding, dict), "prepared tenant RBAC is invalid")
            _require(isinstance(binding.get("metadata"), dict) and
                     binding["metadata"].get("name") == name and
                     binding.get("metadata", {}).get("namespace") == "openclaw-agents" and
                     binding.get("roleRef") == {"apiGroup": "rbac.authorization.k8s.io",
                                                "kind": "ClusterRole", "name": role} and
                     binding.get("subjects") == [{"kind": "ServiceAccount", "name": subject,
                                                  "namespace": "openclaw-system"}],
                     "prepared tenant RBAC is absent or changed")

    def configuration_candidates(self, namespace_id):
        _require(isinstance(namespace_id, str) and namespace_id.startswith("ns_"),
                 "Configuration Namespace ID is invalid")
        selector = ("app.kubernetes.io/managed-by=openclaw-enterprise,"
                    "openclaw.dev/namespace=" + namespace_id)
        listing = self._json("-n", "openclaw-agents", "get", "configmaps",
                             "-l", selector, "-o=json")
        _require(isinstance(listing, dict) and isinstance(listing.get("items"), list),
                 "Configuration ConfigMap list is invalid")
        return listing["items"]


def require_driver_identity(installation):
    """GET /installation is deliberately insufficient at the pinned revision."""
    if not isinstance(installation, dict) or not isinstance(installation.get("id"), str):
        raise Blocked("Enterprise Installation response is invalid")
    raise Blocked("GET /installation cannot prove selected Drivers; activation is blocked")


def reviewed_installation(config):
    candidate = (INSTALLATION_APP / "installation.yaml").read_bytes()
    _require(0 < len(candidate) <= 1048576, "reviewed Installation bytes are invalid")
    digest = hashlib.sha256(candidate).hexdigest()
    try:
        values = json.loads(subprocess.check_output(
            ["yq", "-o=json", ".", str(INSTALLATION_APP / "values.yaml")],
            stderr=subprocess.DEVNULL, timeout=15))
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise Blocked("reviewed Installation chart values are unavailable") from None
    controller = config.get("source", {}).get("images", {}).get("controller")
    _require(isinstance(values, dict) and isinstance(values.get("installation"), dict) and
             isinstance(controller, dict) and isinstance(controller.get("repository"), str) and
             isinstance(controller.get("digest"), str),
             "reviewed Installation chart values are invalid")
    image = controller["repository"] + "@" + controller["digest"]
    _require(values["installation"].get("secretName") ==
             "occ-installation-startup-" + digest[:32] and
             values["installation"].get("key") == "installation.yaml" and
             values.get("controlPlane", {}).get("installationChecksum") == digest and
             values.get("images", {}).get("controller") == image,
             "reviewed Installation and chart binding changed")
    return candidate, digest, image


def prove_driver_identity(config, api, kube):
    candidate, digest, image = reviewed_installation(config)
    before = kube.snapshot(digest)
    installation = api.get("/installation")
    _require(isinstance(installation, dict) and
             isinstance(installation.get("id"), str) and
             installation["id"].startswith("ins_"),
             "Enterprise Installation response is invalid")
    after = kube.snapshot(digest)
    return attest_stable_installation(candidate, digest, installation["id"],
                                     before, after, image)


def check(config, api, kube):
    _validate_config(config)
    return prove_driver_identity(config, api, kube)


def reconcile(config, api, kube, expected_sha):
    _validate_config(config)
    _require(config["activationEnabled"] is False,
             "Enterprise activation awaits the dedicated model credential and protected workflow")
    if not SHA.fullmatch(expected_sha):
        raise Blocked("Expected repository SHA is invalid")
    installation = prove_driver_identity(config, api, kube)
    source_sha = config["source"]["revision"]
    identity_sha = _identity_hash(config)
    with ProtectedJournal(config["privateJournal"]["mountPath"], source_sha, identity_sha) as journal:
        state = dict(journal.state)
        installation_id = installation["installationId"]
        _require(state.get("installationId", installation_id) == installation_id,
                 "journaled Installation identity changed")
        if "installationId" not in state:
            state["installationId"] = installation_id
            journal.save(state)
        namespace_id = reconcile_namespace(config, api, journal, kube)
        configuration = reconcile_configuration(config, api, journal, kube, namespace_id)
        agent = reconcile_agent(config, api, journal, namespace_id, configuration["id"])
        _require(agent["desiredRuntimeState"] == "stopped" and
                 agent.get("activeRevisionId") is None,
                 "inactive Enterprise Agent has a runtime revision")
    return {"namespaceId": namespace_id, "configurationId": configuration["id"],
            "agentId": agent["id"], "desiredRuntimeState": "stopped"}


def verify(config, api, kube):
    # Verification is a read, never an inference probe or implicit deployment.
    _require(config["activationEnabled"] is False,
             "active Enterprise verification awaits protected credential and deployment flow")
    installation = check(config, api, kube)
    journal_path = config["privateJournal"]["mountPath"]
    state, raw = read_journal(journal_path, config["source"]["revision"], _identity_hash(config))
    _require(state.get("installationId") == installation["installationId"],
             "journaled Installation identity changed")
    namespace_id = state.get("namespaceId")
    configuration_id = state.get("configurationId")
    agent_id = state.get("agentId")
    _require(all(isinstance(item, str) for item in (namespace_id, configuration_id, agent_id)) and
             state.get("pending") is None, "Enterprise tenant is incomplete")
    kube.tenant_prepared(namespace_id, require_claimed=True)
    discover_exact(api.get("/namespaces"), config["namespace"]["logicalName"], namespace_id,
                   {"existingNamespace": config["namespace"]["existingNamespace"]})
    namespace = api.get("/namespaces/" + namespace_id)
    _require(isinstance(namespace, dict) and
             namespace.get("id") == namespace_id and
             namespace.get("name") == config["namespace"]["logicalName"] and
             namespace.get("existingNamespace") == config["namespace"]["existingNamespace"] and
             namespace.get("status") == "ready", "Enterprise Namespace readback changed")
    configuration = api.get(f"/namespaces/{namespace_id}/configurations/{configuration_id}")
    _assert_configuration(configuration, namespace_id, configuration_id,
                          desired_configuration(config), state.get("configurationGeneration"))
    candidates = kube.configuration_candidates(namespace_id)
    _require(len(candidates) == 1, "Configuration ConfigMap set is ambiguous")
    recover_configuration(candidates, configuration, "openclaw-agents")
    agents = api.get(f"/namespaces/{namespace_id}/agents")
    discover_exact(agents, config["agent"]["name"], agent_id,
                   {"configurationId": configuration_id})
    agent = api.get(f"/namespaces/{namespace_id}/agents/{agent_id}")
    _assert_agent(agent, config, namespace_id, configuration_id, agent_id)
    _require(agent["desiredRuntimeState"] == "stopped" and
             agent.get("activeRevisionId") is None and
             agent.get("harnessAuth") is None and
             agent.get("servicePrincipalId") == state.get("servicePrincipalId"),
             "inactive Enterprise Agent changed")
    after, second_raw = read_journal(journal_path, config["source"]["revision"], _identity_hash(config))
    _require(raw == second_raw and state == after, "Enterprise journal changed during verification")
    return {"namespaceId": namespace_id, "configurationId": configuration_id,
            "agentId": agent_id, "desiredRuntimeState": "stopped"}


def _identity_hash(config):
    """Bind the journal to tenant identity while allowing model/phase revisions."""
    identity = {"schemaVersion": config["schemaVersion"],
                "sourceRevision": config["source"]["revision"],
                "namespace": config["namespace"],
                "agent": {key: config["agent"][key] for key in ("name", "type")},
                "consoleOrigin": config["privateOrigins"]["console"]}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def desired_configuration(config):
    """Translate the selected OpenRouter wire model to OCE's native provider/model ref.

    The pinned Harness resolver splits at the first slash. A raw
    `openrouter/free` ref would select unsupported provider `openrouter`.
    """
    _validate_config(config)
    model = config["model"]
    native_ref = model["provider"] + "/" + model["id"]
    _require(native_ref == "openai/openrouter/free", "Enterprise native model ref changed")
    return {
        "gateway": {
            "mode": "local", "bind": "lan",
            "controlUi": {"enabled": True, "allowedOrigins": [
                "http://127.0.0.1:18789", "http://localhost:18789"]},
            "auth": {"password": {"source": "env", "provider": "default",
                                  "id": "OPENCLAW_GATEWAY_PASSWORD"}},
            "http": {"endpoints": {"chatCompletions": {"enabled": True}}},
        },
        "agents": {"defaults": {"model": native_ref, "skipBootstrap": True,
                                "models": {native_ref: {"agentRuntime": {"id": "openclaw"}}}}},
        "models": {"providers": {model["provider"]: {
            "baseUrl": model["baseUrl"], "api": model["api"],
            "models": [{"id": model["id"], "name": model["id"]}],
        }}},
    }


def reconcile_namespace(config, api, journal, kube):
    """Create once, then adopt only the exact owned Namespace after API readback."""
    state = dict(journal.state)
    name = config["namespace"]["logicalName"]
    physical = config["namespace"]["existingNamespace"]
    pending = state.get("pending")
    _require(pending is None or pending == {"operation": "namespace-create"} or
             (state.get("namespaceId") is not None and
              pending.get("operation") in ("configuration-create", "agent-create")),
             "another Enterprise operation is pending")
    candidates = api.get("/namespaces")
    _require(isinstance(candidates, list), "Namespace list response is invalid")
    if pending and pending.get("operation") == "namespace-create":
        _require(state.get("namespaceId") is None, "pending Namespace already has an ID")
        matches = [item for item in candidates if isinstance(item, dict) and item.get("name") == name]
        _require(len(matches) == 1, "unknown Namespace create outcome; do not retry")
        candidate = matches[0]
        _require(candidate.get("existingNamespace") == physical and
                 isinstance(candidate.get("id"), str) and candidate["id"].startswith("ns_"),
                 "foreign Namespace recovery candidate")
    else:
        candidate = discover_exact(candidates, name, state.get("namespaceId"),
                                   {"existingNamespace": physical})
        if candidate is None:
            kube.tenant_prepared()
            state["pending"] = {"operation": "namespace-create"}
            journal.save(state)
            try:
                candidate = api.post("/namespaces", {"name": name,
                                                      "existingNamespace": physical})
            except DefinitiveRejection:
                # The pinned 401/403 admission and grant checks run before create.
                # Preserve the intent if a competing Namespace appears meanwhile.
                after_rejection = api.get("/namespaces")
                _require(isinstance(after_rejection, list) and
                         not any(isinstance(item, dict) and item.get("name") == name
                                 for item in after_rejection),
                         "Namespace create outcome changed after rejection")
                state.pop("pending")
                journal.save(state)
                raise
            _require(isinstance(candidate, dict) and candidate.get("name") == name and
                     candidate.get("existingNamespace") == physical and
                     isinstance(candidate.get("id"), str) and candidate["id"].startswith("ns_"),
                     "Namespace create response is invalid")
    namespace_id = candidate["id"]
    _require(isinstance(namespace_id, str) and
             re.fullmatch(r"ns_[A-Za-z0-9_-]{1,100}", namespace_id),
             "Namespace ID is invalid")
    kube.tenant_prepared(namespace_id)
    exact = api.get("/namespaces/" + namespace_id)
    _require(isinstance(exact, dict) and exact.get("id") == namespace_id and
             exact.get("name") == name and exact.get("existingNamespace") == physical and
             exact.get("status") == "ready", "Namespace exact readback changed")
    kube.tenant_prepared(namespace_id, require_claimed=True)
    discover_exact(api.get("/namespaces"), name, namespace_id,
                   {"existingNamespace": physical})
    if state.get("namespaceId") is None:
        state["namespaceId"] = namespace_id
        state.pop("pending", None)
        journal.save(state)
    return namespace_id


def _assert_configuration(item, namespace_id, configuration_id, desired, generation=None):
    _require(isinstance(item, dict) and item.get("id") == configuration_id and
             item.get("namespaceId") == namespace_id and item.get("kind") == "agent" and
             item.get("secretBindings") in (None, {}) and
             item.get("values") == desired and
             type(item.get("generation")) is int and item["generation"] >= 1 and
             (generation is None or item["generation"] == generation),
             "Enterprise Configuration readback changed")


def reconcile_configuration(config, api, journal, kube, namespace_id):
    """Recover an uncertain create from exact owned ConfigMap plus API GET."""
    state = dict(journal.state)
    desired = desired_configuration(config)
    expected_hash = hashlib.sha256(json.dumps(desired, sort_keys=True,
                                               separators=(",", ":")).encode()).hexdigest()
    _require(state.get("desiredHash", expected_hash) == expected_hash,
             "Enterprise desired Configuration changed without a reviewed generation update")
    pending = state.get("pending")
    _require(pending is None or pending.get("operation") == "configuration-create" or
             (state.get("configurationId") is not None and
              pending.get("operation") == "agent-create"),
             "another Enterprise operation is pending")
    configuration_id = state.get("configurationId")
    path = f"/namespaces/{namespace_id}/configurations"
    if configuration_id is None:
        candidates = kube.configuration_candidates(namespace_id)
        _require(isinstance(candidates, list), "Configuration candidates are invalid")
        if pending:
            baseline = set(pending["baselineConfigmapUids"])
            new = [item for item in candidates if isinstance(item, dict) and
                   item.get("metadata", {}).get("uid") not in baseline]
            _require(len(new) == 1, "unknown Configuration create outcome; do not retry")
            candidate = new[0]
            configuration_id = candidate.get("metadata", {}).get("annotations", {}).get(
                "openclaw.dev/configuration-id")
            _require(_valid_resource_id(configuration_id, "cfg_"),
                     "Configuration recovery candidate has no exact ID")
            exact = api.get(path + "/" + configuration_id)
            recover_configuration([candidate], exact, "openclaw-agents")
        else:
            _require(not candidates, "unjournaled Enterprise Configuration may be foreign")
            state["desiredHash"] = expected_hash
            state["pending"] = {"operation": "configuration-create",
                                "baselineConfigmapUids": []}
            journal.save(state)
            try:
                created = api.post(path, {"kind": "agent", "values": desired})
            except DefinitiveRejection:
                # A rejected create can be retried only after a fresh Kubernetes
                # read proves that no Configuration ConfigMap appeared.
                _require(kube.configuration_candidates(namespace_id) == [],
                         "Configuration create outcome changed after rejection")
                state.pop("pending")
                journal.save(state)
                raise
            _require(isinstance(created, dict), "Configuration create response is invalid")
            configuration_id = created.get("id")
            _require(_valid_resource_id(configuration_id, "cfg_"),
                     "Configuration create ID is invalid")
            exact = api.get(path + "/" + configuration_id)
        _assert_configuration(exact, namespace_id, configuration_id, desired)
        candidate = kube.configuration_candidates(namespace_id)
        _require(len(candidate) == 1, "Configuration ConfigMap set is ambiguous")
        recover_configuration(candidate, exact, "openclaw-agents")
        state["configurationId"] = configuration_id
        state["configurationGeneration"] = exact["generation"]
        state.pop("pending", None)
        journal.save(state)
        return exact
    _require(pending is None or pending.get("operation") == "agent-create",
             "journaled Configuration has a pending operation")
    exact = api.get(path + "/" + configuration_id)
    _assert_configuration(exact, namespace_id, configuration_id, desired,
                          state.get("configurationGeneration"))
    candidates = kube.configuration_candidates(namespace_id)
    _require(len(candidates) == 1, "Configuration ConfigMap set is ambiguous")
    recover_configuration(candidates, exact, "openclaw-agents")
    return exact


def _assert_agent(item, config, namespace_id, configuration_id, agent_id):
    _require(isinstance(item, dict) and item.get("id") == agent_id and
             item.get("namespaceId") == namespace_id and
             item.get("name") == config["agent"]["name"] and
             item.get("configurationId") == configuration_id and
             item.get("executionMode") == "embedded" and
             item.get("backendId") is None and
             item.get("status") == "active" and
             isinstance(item.get("servicePrincipalId"), str) and
             bool(item["servicePrincipalId"]),
             "Enterprise Agent readback changed")


def reconcile_agent(config, api, journal, namespace_id, configuration_id):
    """Create/adopt only one fresh, stopped, unauthenticated Embedded Agent."""
    state = dict(journal.state)
    pending = state.get("pending")
    _require(pending is None or pending.get("operation") == "agent-create",
             "another Enterprise operation is pending")
    path = f"/namespaces/{namespace_id}/agents"
    agents = api.get(path)
    _require(isinstance(agents, list), "Enterprise Agent list is invalid")
    name = config["agent"]["name"]
    agent_id = state.get("agentId")
    if agent_id is None:
        if pending:
            baseline = set(pending["baselineAgentIds"])
            new = [item for item in agents if isinstance(item, dict) and
                   item.get("id") not in baseline and item.get("name") == name]
            _require(len(new) == 1,
                     "unknown Agent create outcome; do not retry")
            agent_id = new[0].get("id")
        else:
            _require(not any(isinstance(item, dict) and item.get("name") == name
                             for item in agents),
                     "unjournaled Enterprise Agent may be foreign")
            _require(all(isinstance(item, dict) and isinstance(item.get("id"), str)
                         for item in agents), "Enterprise Agent list is invalid")
            state["pending"] = {"operation": "agent-create",
                                "baselineAgentIds": [item["id"] for item in agents]}
            journal.save(state)
            try:
                created = api.post(path, {"name": name, "configurationId": configuration_id,
                                          "executionMode": "embedded"})
            except DefinitiveRejection:
                # Preserve intent unless an exact fresh list proves no Agent
                # appeared after the authorization rejection.
                after_rejection = api.get(path)
                baseline = state["pending"]["baselineAgentIds"]
                _require(isinstance(after_rejection, list) and
                         all(isinstance(item, dict) and isinstance(item.get("id"), str)
                             for item in after_rejection) and
                         len({item["id"] for item in after_rejection}) == len(after_rejection) and
                         set(baseline) <= {item["id"] for item in after_rejection} and
                         not any(item.get("name") == name for item in after_rejection),
                         "Agent create outcome changed after rejection")
                state.pop("pending")
                journal.save(state)
                raise
            _require(isinstance(created, dict), "Agent create response is invalid")
            agent_id = created.get("id")
        _require(_valid_resource_id(agent_id, "agt_"),
                 "Enterprise Agent ID is invalid")
        exact = api.get(path + "/" + agent_id)
        _assert_agent(exact, config, namespace_id, configuration_id, agent_id)
        _require(exact.get("desiredRuntimeState") == "stopped" and
                 exact.get("activeRevisionId") is None and exact.get("harnessAuth") is None,
                 "new Enterprise Agent is not inactive")
        discover_exact(api.get(path), name, agent_id,
                       {"configurationId": configuration_id})
        state["agentId"] = agent_id
        state["servicePrincipalId"] = exact["servicePrincipalId"]
        state.pop("pending", None)
        journal.save(state)
        return exact
    _require(pending is None, "journaled Agent has a pending operation")
    discover_exact(agents, name, agent_id, {"configurationId": configuration_id})
    exact = api.get(path + "/" + agent_id)
    _assert_agent(exact, config, namespace_id, configuration_id, agent_id)
    _require(exact.get("servicePrincipalId") == state.get("servicePrincipalId"),
             "journaled Agent principal changed")
    _require(exact.get("desiredRuntimeState") == "stopped" and
             exact.get("activeRevisionId") is None and exact.get("harnessAuth") is None,
             "journaled Agent is not inactive")
    return exact


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
    origins = config.get("privateOrigins")
    if not isinstance(origins, dict) or origins.get("console") != CONSOLE_ORIGIN:
        raise Blocked("Enterprise console origin changed")
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
    model = config.get("model", {})
    secrets = config.get("secrets", {})
    if not isinstance(model, dict) or model != APPROVED_MODEL:
        raise Blocked("explicit model must use approved OpenRouter transport")
    if (not isinstance(secrets, dict) or
            secrets.get("modelApiKey") != "/homelab/openclaw-enterprise/model-api-key"):
        raise Blocked("dedicated model key reference changed")


def _require(condition, reason):
    if not condition:
        raise Blocked(reason)


def _valid_resource_id(value, prefix):
    return (isinstance(value, str) and value.startswith(prefix) and
            re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value[len(prefix):]) is not None)


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


def _resource_version(metadata):
    version = metadata.get("resourceVersion")
    _require(isinstance(version, str) and bool(version.strip()),
             "Installation workload resource version is missing")
    return version


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
    entrypoint = "apps/controller/src/" + ("server" if component == "api" else "worker") + ".mjs"
    _require(container.get("command") in (None, []) and container.get("args") == [entrypoint],
             "Installation controller entrypoint changed")
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
               "deploymentUids": {}, "replicaSetUids": {}, "podUids": {},
               "deploymentResourceVersions": {}, "replicaSetResourceVersions": {},
               "podResourceVersions": {}}
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
        _require(len(replicasets) >= 1 and len(pods) == 1,
                 "Installation workload has ambiguous replicas")
        pod = pods[0]
        for historical in replicasets:
            historical_meta = historical["metadata"]
            _controller_owner(historical_meta, "Deployment", dep_meta["uid"], name)
            _require(historical_meta.get("namespace") == "openclaw-system" and
                     isinstance(historical_meta.get("uid"), str) and
                     isinstance(historical_meta.get("name"), str),
                     "Installation ReplicaSet is foreign")
        pod_owners = [item for item in pod["metadata"].get("ownerReferences", [])
                      if item.get("controller") is True and item.get("kind") == "ReplicaSet"]
        active = [item for item in replicasets if len(pod_owners) == 1 and
                  item["metadata"].get("uid") == pod_owners[0].get("uid") and
                  item["metadata"].get("name") == pod_owners[0].get("name")]
        _require(len(active) == 1, "Installation Pod has no unique owned ReplicaSet")
        rs = active[0]
        rs_meta, pod_meta = rs["metadata"], pod["metadata"]
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
        receipt["deploymentResourceVersions"][component] = _resource_version(dep_meta)
        receipt["replicaSetUids"][component] = rs_meta["uid"]
        receipt["replicaSetResourceVersions"][component] = _resource_version(rs_meta)
        receipt["podUids"][component] = pod_meta["uid"]
        receipt["podResourceVersions"][component] = _resource_version(pod_meta)
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
    principal_bindings = [binding for binding in bindings if
                          binding.get("subjectKind") == "identity" and
                          binding.get("subjectId") == principal_id]
    exact_bindings = [binding for binding in principal_bindings if
                      binding.get("namespaceId") == namespace_id and
                      binding.get("roleId") == role_id and
                      binding.get("resourceKind") == "secret" and
                      binding.get("resourceId") == secret_id]
    if len(exact_bindings) != 1 or len(principal_bindings) != 1:
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
                  (field in ID_PREFIXES and
                   not _valid_resource_id(value, ID_PREFIXES[field]))):
                raise Blocked("Journal resource identity is invalid")
        pending = state.get("pending")
        if pending is not None:
            if (not isinstance(pending, dict) or
                    set(pending) - {"operation", "baselineRevisionIds",
                                    "baselineConfigmapUids", "baselineAgentIds"} or
                    pending.get("operation") not in ("namespace-create", "configuration-create",
                                                     "agent-create", "deploy") or
                    not isinstance(pending.get("baselineRevisionIds", []), list) or
                    any(not isinstance(item, str) or not item.startswith("rev_") or
                        not re.fullmatch(r"[A-Za-z0-9._~:@/-]{1,200}", item)
                        for item in pending.get("baselineRevisionIds", [])) or
                    any(not isinstance(pending.get(key, []), list) or
                        any(not isinstance(item, str) or not re.fullmatch(
                            r"[A-Za-z0-9._~:@/-]{1,200}", item)
                            for item in pending.get(key, []))
                        for key in ("baselineConfigmapUids", "baselineAgentIds"))):
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


def read_journal(path, source_sha, config_sha):
    """Read a protected journal without creating a lock or changing the file."""
    candidate = Path(path)
    _require(candidate.is_absolute() and candidate.parent.resolve() == candidate.parent and
             candidate.parent.is_dir(), "Journal path is not a real private path")
    parent_stat = candidate.parent.stat()
    _require(parent_stat.st_uid == os.getuid() and stat.S_IMODE(parent_stat.st_mode) == 0o700,
             "Journal parent owner or mode is unsafe")
    ProtectedJournal._check_file(candidate)
    _require(candidate.is_file(), "Enterprise journal is missing")
    raw = candidate.read_bytes()
    _require(len(raw) <= 65536, "Journal is oversized")
    try:
        document = json.loads(raw)
    except ValueError:
        raise Blocked("Enterprise journal is invalid JSON") from None
    _require(isinstance(document, dict) and document.get("schemaVersion") == 1 and
             document.get("sourceSha") == source_sha and document.get("configSha") == config_sha,
             "Journal source or desired input changed")
    state = document.get("state")
    ProtectedJournal._validate_state(state)
    return state, raw


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
        kube = Kubernetes()
        if args.command == "reconcile":
            reconcile(config, api, kube, args.expected_sha)
        elif args.command == "verify":
            verify(config, api, kube)
        else:
            check(config, api, kube)
    except (Blocked, OSError, ValueError, KeyError) as error:
        print(f"OpenClaw Enterprise {args.command} blocked: {error}", file=sys.stderr)
        return 1
    print(f"OpenClaw Enterprise {args.command} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
