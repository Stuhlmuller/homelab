#!/usr/bin/env python3
"""Fail-closed OpenClaw Enterprise reconciliation entrypoint.

Read-only checks attest the reviewed startup file and current controller Pods.
The committed activation switch is disabled. A later protected workflow can
reconcile the supported credential, grant, deployment and stop lifecycle.
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
import secrets as secure_random
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
IN_CLUSTER_KUBE_SERVER = "https://10.1.0.199:6443"
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
    "bindingId", "revisionId", "firstRevisionId", "desiredHash", "pending", "secretName",
    "roleName", "modelKeyVersion", "revisionIds", "backup",
})
ID_PREFIXES = {
    "installationId": "ins_", "namespaceId": "ns_", "secretId": "sec_",
    "configurationId": "cfg_", "agentId": "agt_", "revisionId": "rev_",
    "firstRevisionId": "rev_",
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
        if not isinstance(body, dict):
            raise Blocked("Enterprise API mutation body is invalid")
        return self._request("POST", path, body, 201)

    def post_ok(self, path, body):
        return self._request("POST", path, body, 200)

    def post_accepted(self, path, body=None):
        return self._request("POST", path, body, 202)

    def patch(self, path, body):
        return self._request("PATCH", path, body, 200)

    def revisions_page(self, path, cursor=None):
        _require(cursor is None or isinstance(cursor, str) and
                 re.fullmatch(r"v1\.[1-9][0-9]{0,14}", cursor),
                 "Enterprise revision cursor is invalid")
        suffix = "?limit=100" + ("&cursor=" + cursor if cursor else "")
        return self._request("GET", path + suffix, None, 200, envelope=True,
                             allow_revision_query=True)

    def _request(self, method, path, body, expected_status, envelope=False,
                 allow_revision_query=False):
        if (not path.startswith("/") or "#" in path or
                ("?" in path and not allow_revision_query)):
            raise Blocked("Enterprise API path is not exact")
        if method in ("POST", "PATCH") and body is not None and not isinstance(body, dict):
            raise Blocked("Enterprise API mutation body is invalid")
        if method == "PATCH" and body is None:
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
        return payload if envelope else payload["data"]


class Kubernetes:
    """Read exact installed controller objects without printing Secret data."""

    @staticmethod
    def _trusted_context(context):
        clusters = context.get("clusters") if isinstance(context, dict) else None
        _require(isinstance(clusters, list) and len(clusters) == 1 and
                 isinstance(clusters[0], dict) and
                 isinstance(clusters[0].get("cluster"), dict),
                 "Kubernetes proof context changed")
        cluster = clusters[0]["cluster"]
        server = cluster.get("server")
        _require(server in (KUBE_SERVER, IN_CLUSTER_KUBE_SERVER) and
                 not cluster.get("insecure-skip-tls-verify"),
                 "Kubernetes proof context changed")
        if server == IN_CLUSTER_KUBE_SERVER:
            users = context.get("users")
            _require(cluster.get("certificate-authority") ==
                     "/var/run/oce-operator-api/ca.crt" and
                     isinstance(users, list) and len(users) == 1 and
                     users[0].get("user") == {
                         "tokenFile": "/var/run/oce-operator-api/token"},
                     "Kubernetes in-cluster proof credentials changed")

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
        self._trusted_context(context)
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
        self._trusted_context(context)
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
        # A label selector would hide ownership drift before the create gate.
        listing = self._json("-n", "openclaw-agents", "get", "configmaps", "-o=json")
        _require(isinstance(listing, dict) and isinstance(listing.get("items"), list),
                 "Configuration ConfigMap list is invalid")
        candidates = []
        for item in listing["items"]:
            metadata = item.get("metadata") if isinstance(item, dict) else None
            _require(isinstance(metadata, dict), "Configuration ConfigMap list is invalid")
            labels = metadata.get("labels") or {}
            annotations = metadata.get("annotations") or {}
            _require(isinstance(labels, dict) and isinstance(annotations, dict),
                     "Configuration ConfigMap metadata is invalid")
            name = metadata.get("name")
            if ((isinstance(name, str) and name.startswith("cfg-")) or
                    labels.get("app.kubernetes.io/managed-by") == "openclaw-enterprise" or
                    any(key.startswith("openclaw.dev/") for key in (*labels, *annotations))):
                candidates.append(item)
        return candidates

    def tenant_pods_absent(self):
        # Do not filter by OCE labels: a foreign or unlabelled Pod can still write.
        # kubectl get pods -o=json synthesizes List without a resource version.
        listing = self._json("get", "--raw", "/api/v1/namespaces/openclaw-agents/pods")
        _require(isinstance(listing, dict) and listing.get("kind") == "PodList" and
                 isinstance(listing.get("metadata"), dict) and
                 isinstance(listing["metadata"].get("resourceVersion"), str) and
                 bool(listing["metadata"]["resourceVersion"]) and
                 listing["metadata"].get("continue") in (None, "") and
                 listing.get("items") == [],
                 "Enterprise tenant still has Pods or Pod list is uncertain")


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


def reconcile(config, api, kube, expected_sha, model_credential=None):
    _validate_config(config)
    if not SHA.fullmatch(expected_sha):
        raise Blocked("Expected repository SHA is invalid")
    if config["activationEnabled"]:
        _require(isinstance(model_credential, dict) and
                 set(model_credential) == {"version", "key"} and
                 type(model_credential["version"]) is int and
                 model_credential["version"] > 0 and
                 isinstance(model_credential["key"], str) and
                 model_credential["key"] not in ("", "REPLACE_ME"),
                 "active Enterprise reconciliation requires a protected model credential")
        result = reconcile_active(config, api, kube, model_credential)
        _require(config["privateOrigins"]["nativeOrigin"] is not None,
                 "native origin needs an owner-session return and reviewed Configuration update")
        return result
    installation = prove_driver_identity(config, api, kube)
    source_sha = config["source"]["revision"]
    identity_sha = _identity_hash(config)
    with ProtectedJournal(config["privateJournal"]["mountPath"], source_sha, identity_sha) as journal:
        state = dict(journal.state)
        installation_id = installation["installationId"]
        _require(state.get("installationId", installation_id) == installation_id,
                 "journaled Installation identity changed")
        if config["privateOrigins"]["nativeOrigin"] is not None:
            _require(_valid_resource_id(state.get("revisionId"), "rev_") and
                     type(state.get("modelKeyVersion")) is int,
                     "native origin requires the first active revision")
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
    # The same durable lock serializes readback with an interrupted mutation Job.
    with ProtectedJournal(config["privateJournal"]["mountPath"],
                          config["source"]["revision"], _identity_hash(config),
                          create_lock=False):
        return _verify_locked(config, api, kube)


def _verify_locked(config, api, kube):
    # Verification is a read, never an inference probe or implicit deployment.
    _validate_config(config)
    if config["activationEnabled"]:
        return verify_active(config, api, kube)
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
    native_origin = config["privateOrigins"]["nativeOrigin"]
    gateway = {
        "mode": "local", "bind": "lan",
        "controlUi": ({"enabled": False} if native_origin is None else
                      {"enabled": True, "allowedOrigins": [native_origin]}),
        "auth": {"password": {"source": "env", "provider": "default",
                              "id": "OPENCLAW_GATEWAY_PASSWORD"}},
        "http": {"endpoints": {"chatCompletions": {"enabled": True}}},
    }
    if native_origin is not None:
        gateway["publicOrigin"] = native_origin
        gateway["auth"].update({
            "mode": "trusted-proxy",
            "trustedProxy": {"userHeader": "x-occ-identity",
                             "allowUsers": ["occ-workspace-files"],
                             "deviceAutoApprove": {"enabled": True,
                                                   "scopes": ["operator.admin"]}},
            "identityScopes": {"occ-workspace-files": ["operator.admin"]},
        })
    return {
        "gateway": gateway,
        "agents": {"defaults": {"model": native_ref, "skipBootstrap": True,
                                "models": {native_ref: {"agentRuntime": {"id": "openclaw"}}}}},
        "tools": {"deny": ["*"]},
        "secrets": {"providers": {"model": {"source": "env", "allowlist": ["OPENAI_API_KEY"]}}},
        "models": {"providers": {model["provider"]: {
            "baseUrl": model["baseUrl"], "api": model["api"],
            "apiKey": {"source": "env", "provider": "model", "id": "OPENAI_API_KEY"},
            "models": [{"id": model["id"], "name": model["id"]}],
        }}},
    }


def admitted_revision_configuration(config):
    """Pinned OCC admission for this profile's Kubernetes Compute revision.

    The reviewed Installation omits logging, so upstream defaults its level to
    info. Kubernetes Compute does not own runtime logging; no Sandbox is selected.
    Keep saved Configuration values untouched and compare the revision exactly.
    """
    values = desired_configuration(config)
    return {**values,
            "logging": {"level": "info", "consoleLevel": "info", "consoleStyle": "json"},
            "diagnostics": {"otel": {"logs": False}}}


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
                # A definitive rejection cannot own a later competing Namespace.
                state.pop("pending")
                journal.save(state)
                after_rejection = api.get("/namespaces")
                _require(isinstance(after_rejection, list) and
                         not any(isinstance(item, dict) and item.get("name") == name
                                 for item in after_rejection),
                         "Namespace create outcome changed after rejection")
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
                # A definitive rejection cannot own a later competing ConfigMap.
                state.pop("pending")
                journal.save(state)
                _require(kube.configuration_candidates(namespace_id) == [],
                         "Configuration create outcome changed after rejection")
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
    # A metadata-only read omits these saved settings; absence is safe only on
    # the complete Agent variant with a readable harnessAuth field.
    _require("configurationReadError" not in item and "harnessAuth" in item and
             item.get("plugins") in (None, {}) and
             item.get("pluginApprovers") in (None, []) and
             item.get("repositoryBindings") in (None, []) and
             item.get("repositoryAccess") is None and
             item.get("credentialSources") in (None, []),
             "Enterprise Agent has foreign integrations or unreadable settings")


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
                # A definitive rejection cannot own a later competing Agent.
                baseline = state["pending"]["baselineAgentIds"]
                state.pop("pending")
                journal.save(state)
                after_rejection = api.get(path)
                _require(isinstance(after_rejection, list) and
                         all(isinstance(item, dict) and isinstance(item.get("id"), str)
                             for item in after_rejection) and
                         len({item["id"] for item in after_rejection}) == len(after_rejection) and
                         set(baseline) <= {item["id"] for item in after_rejection} and
                         not any(item.get("name") == name for item in after_rejection),
                         "Agent create outcome changed after rejection")
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


def _safe_segment(value, label):
    _require(isinstance(value, str) and
             re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value),
             f"Enterprise {label} is not a safe API ID")
    return value


def _assert_model_secret(item, namespace_id, secret_id, name, agent_id):
    expected_ref = {"kind": "secret", "namespaceId": namespace_id, "id": secret_id}
    consumers = item.get("consumers") if isinstance(item, dict) else None
    _require(isinstance(item, dict) and item.get("id") == secret_id and
             item.get("namespaceId") == namespace_id and item.get("name") == name and
             item.get("ref") == expected_ref and isinstance(consumers, dict) and
             consumers.get("configurations") == [] and
             consumers.get("credentialSources") == [] and
             consumers.get("provisioningRequests") == [] and
             consumers.get("truncated") is False and consumers.get("unreadable") == 0 and
             isinstance(consumers.get("agents"), list) and
             set(consumers["agents"]) <= {agent_id},
             "Enterprise model Secret ownership or consumers changed")


def _unique_model_secret(api, path, secret_id, name):
    visible = api.get(path)
    _require(isinstance(visible, list) and
             len([item for item in visible if isinstance(item, dict) and
                  item.get("name") == name]) == 1 and
             any(isinstance(item, dict) and item.get("id") == secret_id and
                 item.get("name") == name for item in visible),
             "Enterprise model Secret list is ambiguous")


def reconcile_model_secret(config, api, journal, credential):
    """Create one high-entropy named OCC Secret; never journal its value."""
    state = dict(journal.state)
    namespace_id = state["namespaceId"]
    agent_id = state["agentId"]
    path = f"/namespaces/{namespace_id}/secrets"
    _require(state.get("modelKeyVersion", credential["version"]) == credential["version"],
             "model key version changed; use a reviewed rotation")
    secret_id = state.get("secretId")
    if secret_id is None:
        pending = state.get("pending")
        _require(pending is None or pending.get("operation") == "secret-create",
                 "another Enterprise operation is pending")
        visible = api.get(path)
        _require(isinstance(visible, list) and
                 all(isinstance(item, dict) and isinstance(item.get("id"), str)
                     for item in visible), "Enterprise Secret list is invalid")
        name = state.get("secretName") or "oce-claw-openrouter-" + secure_random.token_hex(16)
        _require(re.fullmatch(r"oce-claw-openrouter-[0-9a-f]{32}", name),
                 "journaled model Secret name is invalid")
        if pending:
            baseline = set(pending["baselineSecretIds"])
            _require(baseline <= {item["id"] for item in visible},
                     "Enterprise Secret baseline changed")
            new = [item for item in visible if item["id"] not in baseline]
            _require(len(new) == 1 and new[0].get("name") == name,
                     "unknown model Secret create outcome; do not retry")
            secret_id = new[0]["id"]
        else:
            _require(not any(item.get("name") == name for item in visible),
                     "unjournaled Enterprise model Secret may be foreign")
            state["secretName"] = name
            state["modelKeyVersion"] = credential["version"]
            state["pending"] = {"operation": "secret-create",
                                "baselineSecretIds": [item["id"] for item in visible]}
            journal.save(state)
            try:
                created = api.post(path, {"name": name, "value": credential["key"]})
            except DefinitiveRejection:
                after = api.get(path)
                _require(isinstance(after, list) and
                         {item.get("id") for item in after if isinstance(item, dict)} ==
                         set(state["pending"]["baselineSecretIds"]) and
                         len(after) == len(state["pending"]["baselineSecretIds"]),
                         "model Secret create outcome changed after rejection")
                state.pop("pending")
                state.pop("secretName")
                state.pop("modelKeyVersion")
                journal.save(state)
                raise
            _require(isinstance(created, dict) and created.get("name") == name,
                     "Enterprise model Secret create response is invalid")
            secret_id = created.get("id")
        secret_id = _safe_segment(secret_id, "model Secret")
        exact = api.get(path + "/" + secret_id)
        _assert_model_secret(exact, namespace_id, secret_id, name, agent_id)
        _unique_model_secret(api, path, secret_id, name)
        state["secretId"] = secret_id
        state.pop("pending", None)
        journal.save(state)
        return exact
    _require(state.get("pending", {}).get("operation") != "secret-create",
             "journaled model Secret has pending creation")
    secret_id = _safe_segment(secret_id, "model Secret")
    exact = api.get(path + "/" + secret_id)
    _assert_model_secret(exact, namespace_id, secret_id, state.get("secretName"), agent_id)
    _unique_model_secret(api, path, secret_id, state.get("secretName"))
    return exact


def _assert_model_role(item, namespace_id, role_id, name):
    _require(isinstance(item, dict) and item.get("id") == role_id and
             item.get("namespaceId") == namespace_id and item.get("name") == name and
             item.get("permissions") == [{"action": "operate", "resourceKind": "secret"}],
             "Enterprise model Secret Role changed")


def _assert_model_binding(item, namespace_id, binding_id, principal_id, role_id, secret_id):
    _require(isinstance(item, dict) and item.get("id") == binding_id and
             item.get("namespaceId") == namespace_id and
             item.get("subjectKind") == "identity" and
             item.get("subjectId") == principal_id and
             item.get("roleId") == role_id and
             item.get("resourceKind") == "secret" and
             item.get("resourceId") == secret_id,
             "Enterprise model Secret AccessBinding changed")


def reconcile_model_grant(api, journal):
    """Journal the sole exact Secret-operate Role and Agent-principal binding."""
    state = dict(journal.state)
    namespace_id = state["namespaceId"]
    role_path = f"/namespaces/{namespace_id}/iam/roles"
    binding_path = f"/namespaces/{namespace_id}/iam/access-bindings"
    permission = [{"action": "operate", "resourceKind": "secret"}]
    roles = api.get(role_path)
    _require(isinstance(roles, list) and
             all(isinstance(item, dict) and isinstance(item.get("id"), str)
                 for item in roles),
             "Enterprise IAM Role list is invalid")
    role_id = state.get("roleId")
    if role_id is None:
        pending = state.get("pending")
        _require(pending is None or pending.get("operation") == "role-create",
                 "another Enterprise operation is pending")
        name = state.get("roleName") or "oce-claw-secret-" + secure_random.token_hex(16)
        _require(re.fullmatch(r"oce-claw-secret-[0-9a-f]{32}", name),
                 "journaled model Role name is invalid")
        if pending:
            baseline = set(pending["baselineRoleIds"])
            _require(baseline <= {item["id"] for item in roles},
                     "Enterprise Role baseline changed")
            new = [item for item in roles if item.get("id") not in baseline]
            _require(len(new) == 1 and new[0].get("name") == name,
                     "unknown model Role create outcome; do not retry")
            role_id = new[0]["id"]
        else:
            _require(not any(item.get("permissions") == permission for item in roles),
                     "unjournaled exact model Role may be foreign")
            state["roleName"] = name
            state["pending"] = {"operation": "role-create",
                                "baselineRoleIds": [item["id"] for item in roles]}
            journal.save(state)
            try:
                created = api.post(role_path, {"name": name, "permissions": permission})
            except DefinitiveRejection:
                after = api.get(role_path)
                _require(isinstance(after, list) and
                         len(after) == len(state["pending"]["baselineRoleIds"]) and
                         {item.get("id") for item in after if isinstance(item, dict)} ==
                         set(state["pending"]["baselineRoleIds"]),
                         "model Role create outcome changed after rejection")
                state.pop("pending")
                journal.save(state)
                raise
            _require(isinstance(created, dict) and created.get("name") == name,
                     "Enterprise model Role create response is invalid")
            role_id = created.get("id")
        role_id = _safe_segment(role_id, "model Role")
        exact = api.get(role_path + "/" + role_id)
        _assert_model_role(exact, namespace_id, role_id, name)
        state["roleId"] = role_id
        state.pop("pending", None)
        journal.save(state)
    else:
        _require(state.get("pending", {}).get("operation") != "role-create",
                 "journaled model Role has pending creation")
        role_id = _safe_segment(role_id, "model Role")
        exact = api.get(role_path + "/" + role_id)
        _assert_model_role(exact, namespace_id, role_id, state.get("roleName"))
    roles = api.get(role_path)
    _require(isinstance(roles, list) and all(isinstance(item, dict) for item in roles),
             "Enterprise IAM Role list is invalid")
    _require(len([item for item in roles if item.get("permissions") == permission]) == 1,
             "ambiguous exact model Role")

    state = dict(journal.state)
    bindings = api.get(binding_path)
    _require(isinstance(bindings, list) and
             all(isinstance(item, dict) and isinstance(item.get("id"), str)
                 for item in bindings),
             "Enterprise IAM AccessBinding list is invalid")
    principal_id = state["servicePrincipalId"]
    secret_id = state["secretId"]
    binding_id = state.get("bindingId")
    if binding_id is None:
        pending = state.get("pending")
        _require(pending is None or pending.get("operation") == "binding-create",
                 "another Enterprise operation is pending")
        if pending:
            baseline = set(pending["baselineBindingIds"])
            _require(baseline <= {item["id"] for item in bindings},
                     "Enterprise AccessBinding baseline changed")
            new = [item for item in bindings if item.get("id") not in baseline]
            _require(len(new) == 1, "unknown model AccessBinding create outcome; do not retry")
            binding_id = new[0]["id"]
        else:
            _require(not any(item.get("subjectKind") == "identity" and
                             item.get("subjectId") == principal_id for item in bindings),
                     "unjournaled Agent grant may be foreign")
            state["pending"] = {"operation": "binding-create",
                                "baselineBindingIds": [item["id"] for item in bindings]}
            journal.save(state)
            try:
                created = api.post(binding_path, {
                    "subjectKind": "identity", "subjectId": principal_id,
                    "roleId": role_id, "resourceKind": "secret", "resourceId": secret_id})
            except DefinitiveRejection:
                after = api.get(binding_path)
                _require(isinstance(after, list) and
                         len(after) == len(state["pending"]["baselineBindingIds"]) and
                         {item.get("id") for item in after if isinstance(item, dict)} ==
                         set(state["pending"]["baselineBindingIds"]),
                         "model AccessBinding create outcome changed after rejection")
                state.pop("pending")
                journal.save(state)
                raise
            _require(isinstance(created, dict), "Enterprise AccessBinding create response is invalid")
            binding_id = created.get("id")
        binding_id = _safe_segment(binding_id, "model AccessBinding")
        exact = api.get(binding_path + "/" + binding_id)
        _assert_model_binding(exact, namespace_id, binding_id, principal_id, role_id, secret_id)
        state["bindingId"] = binding_id
        state.pop("pending", None)
        journal.save(state)
    else:
        _require(state.get("pending", {}).get("operation") != "binding-create",
                 "journaled model AccessBinding has pending creation")
        binding_id = _safe_segment(binding_id, "model AccessBinding")
        exact = api.get(binding_path + "/" + binding_id)
        _assert_model_binding(exact, namespace_id, binding_id, principal_id, role_id, secret_id)
    roles = api.get(role_path)
    bindings = api.get(binding_path)
    _require(isinstance(roles, list) and isinstance(bindings, list) and
             all(isinstance(item, dict) for item in roles + bindings),
             "Enterprise IAM grant lists are invalid")
    exact_model_grant(roles, bindings, namespace_id, principal_id, secret_id)
    return role_id, binding_id


def _model_auth(namespace_id, secret_id):
    return {"method": "api_key", "source": {
        "kind": "secret", "namespaceId": namespace_id, "id": secret_id}}


def bind_model_secret(config, api, journal):
    state = dict(journal.state)
    namespace_id, agent_id = state["namespaceId"], state["agentId"]
    path = f"/namespaces/{namespace_id}/agents/{agent_id}"
    desired = _model_auth(namespace_id, state["secretId"])
    agent = api.get(path)
    _assert_agent(agent, config, namespace_id, state["configurationId"], agent_id)
    _require(agent.get("servicePrincipalId") == state["servicePrincipalId"],
             "Enterprise Agent principal changed")
    if agent.get("harnessAuth") == desired:
        if state.get("pending") == {"operation": "agent-bind"}:
            state.pop("pending")
            journal.save(state)
        return agent
    _require(agent.get("harnessAuth") is None and state.get("revisionId") is None and
             agent.get("activeRevisionId") is None and
             agent.get("desiredRuntimeState") == "stopped",
             "Enterprise Agent has a foreign or active model binding")
    _require(state.get("pending") in (None, {"operation": "agent-bind"}),
             "another Enterprise operation is pending")
    state["pending"] = {"operation": "agent-bind"}
    journal.save(state)
    try:
        patched = api.patch(path, {"configurationId": state["configurationId"],
                                   "harnessAuth": desired})
    except DefinitiveRejection:
        after = api.get(path)
        _assert_agent(after, config, namespace_id, state["configurationId"], agent_id)
        _require(after.get("servicePrincipalId") == state["servicePrincipalId"] and
                 after.get("harnessAuth") is None and
                 after.get("desiredRuntimeState") == "stopped" and
                 after.get("activeRevisionId") is None,
                 "Agent binding outcome changed after rejection")
        state.pop("pending")
        journal.save(state)
        raise
    _require(isinstance(patched, dict) and patched.get("id") == agent_id,
             "Enterprise Agent binding response changed")
    exact = api.get(path)
    _assert_agent(exact, config, namespace_id, state["configurationId"], agent_id)
    _require(exact.get("servicePrincipalId") == state["servicePrincipalId"] and
             exact.get("desiredRuntimeState") == "stopped" and
             exact.get("activeRevisionId") is None and
             exact.get("harnessAuth") == desired,
             "Enterprise Agent model binding did not persist")
    state.pop("pending")
    journal.save(state)
    return exact


def ensure_runtime_credentials(api, journal):
    """Upstream reuses a complete owned transport group on repeated POST."""
    state = dict(journal.state)
    path = f"/namespaces/{state['namespaceId']}/agents/{state['agentId']}/runtime-credentials"
    status = api.get(path)
    _require(isinstance(status, dict) and type(status.get("transportConfigured")) is bool,
             "Enterprise runtime credential status is invalid")
    if status["transportConfigured"]:
        if state.get("pending") == {"operation": "runtime-credentials"}:
            state.pop("pending")
            journal.save(state)
        return
    _require(state.get("revisionId") is None and
             state.get("pending") in (None, {"operation": "runtime-credentials"}),
             "Enterprise runtime credential outcome is unresolved")
    state["pending"] = {"operation": "runtime-credentials"}
    journal.save(state)
    try:
        created = api.post_ok(path, {})
    except DefinitiveRejection:
        # The pinned Kubernetes driver rereads both credential groups and only
        # creates missing groups, so even a partial group is safe to retry.
        _require(api.get(path) == {"transportConfigured": False},
                 "runtime credential outcome changed after rejection")
        state.pop("pending")
        journal.save(state)
        raise
    _require(isinstance(created, dict) and created.get("transportConfigured") is True and
             api.get(path) == {"transportConfigured": True},
             "Enterprise runtime credentials were not confirmed")
    state.pop("pending")
    journal.save(state)


def list_agent_revisions(api, namespace_id, agent_id):
    """Read all revision pages; incomplete history cannot prove a deploy baseline."""
    path = f"/namespaces/{namespace_id}/agents/{agent_id}/revisions"
    items, seen_ids, seen_cursors = [], set(), set()
    cursor = None
    for _ in range(100):
        page = api.revisions_page(path, cursor)
        _require(isinstance(page, dict) and isinstance(page.get("data"), list) and
                 isinstance(page.get("meta"), dict),
                 "Enterprise revision page is invalid")
        for item in page["data"]:
            _require(isinstance(item, dict) and
                     _valid_resource_id(item.get("id"), "rev_") and
                     item.get("agentId") == agent_id and
                     item.get("namespaceId") == namespace_id and
                     item["id"] not in seen_ids,
                     "Enterprise revision history changed")
            seen_ids.add(item["id"])
            items.append(item)
        next_cursor = page["meta"].get("nextCursor")
        if next_cursor is None:
            return items
        _require(isinstance(next_cursor, str) and
                 re.fullmatch(r"v1\.[1-9][0-9]{0,14}", next_cursor) and
                 next_cursor not in seen_cursors,
                 "Enterprise revision pagination is invalid")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    raise Blocked("Enterprise revision history exceeds bounded read")


def _assert_active_revision(item, config, state):
    _require(isinstance(item, dict) and isinstance(item.get("harness"), dict) and
             "configurationReadError" not in item and
             item.get("id") == state.get("revisionId") and
             item.get("namespaceId") == state["namespaceId"] and
             item.get("agentId") == state["agentId"] and
             item.get("configurationId") == state["configurationId"] and
             type(item.get("configurationGeneration")) is int and
             item.get("configurationGeneration") == state["configurationGeneration"] and
             item.get("configurationKind") == "agent" and
             item.get("backendId") is None and
             item.get("configuration") == admitted_revision_configuration(config) and
             item.get("harnessAuth") == _model_auth(state["namespaceId"], state["secretId"]) and
             item.get("harness", {}).get("id") == "openclaw" and
             item.get("harness", {}).get("mode") == "embedded" and
             item.get("secretBindings") in (None, {}) and
             item.get("plugins") is None and
             item.get("pluginApprovers") in (None, []) and
             item.get("repositoryCredentials") is None and
             item.get("credentialSources") in (None, []),
             "Enterprise active revision changed")


def reconcile_deployment(config, api, journal):
    state = dict(journal.state)
    namespace_id, agent_id = state["namespaceId"], state["agentId"]
    path = f"/namespaces/{namespace_id}/agents/{agent_id}"
    revisions = list_agent_revisions(api, namespace_id, agent_id)
    revision_id = state.get("revisionId")
    if revision_id is None:
        pending = state.get("pending")
        _require(pending is None or pending.get("operation") == "deploy",
                 "another Enterprise operation is pending")
        if pending:
            revision_id = recover_revision(
                revisions, set(pending["baselineRevisionIds"]), agent_id,
                state["configurationId"], state["configurationGeneration"])
        else:
            _require(not revisions, "unjournaled Enterprise revision may be foreign")
            draft = api.get(path)
            _assert_agent(draft, config, namespace_id, state["configurationId"], agent_id)
            _require(draft.get("servicePrincipalId") == state["servicePrincipalId"] and
                     draft.get("harnessAuth") == _model_auth(namespace_id, state["secretId"]) and
                     draft.get("desiredRuntimeState") == "stopped" and
                     draft.get("activeRevisionId") is None,
                     "Enterprise deploy draft changed")
            state["pending"] = {"operation": "deploy", "baselineRevisionIds": []}
            journal.save(state)
            try:
                created = api.post_accepted(path + "/deploy")
            except DefinitiveRejection:
                _require(list_agent_revisions(api, namespace_id, agent_id) == [],
                         "deploy outcome changed after rejection")
                after = api.get(path)
                _assert_agent(after, config, namespace_id, state["configurationId"], agent_id)
                _require(after.get("servicePrincipalId") == state["servicePrincipalId"] and
                         after.get("desiredRuntimeState") == "stopped" and
                         after.get("activeRevisionId") is None,
                         "deploy Agent state changed after rejection")
                state.pop("pending")
                journal.save(state)
                raise
            _require(isinstance(created, dict) and
                     created.get("agentId") == agent_id and
                     created.get("namespaceId") == namespace_id and
                     created.get("configurationId") == state["configurationId"] and
                     created.get("configurationGeneration") == state["configurationGeneration"],
                     "Enterprise deploy response changed")
            revision_id = created.get("id")
        _require(_valid_resource_id(revision_id, "rev_"),
                 "Enterprise revision ID is invalid")
        state["revisionId"] = revision_id
        exact = api.get(path + "/revisions/" + revision_id)
        _assert_active_revision(exact, config, state)
        state.pop("pending")
        journal.save(state)
    else:
        _require(state.get("pending") is None, "journaled revision has pending operation")
        _require(len([item for item in revisions if item.get("id") == revision_id]) == 1 and
                 len(revisions) == 1, "Enterprise revision history changed")
        exact = api.get(path + "/revisions/" + revision_id)
        _assert_active_revision(exact, config, state)
    deployment = api.get(path + "/deployments/" + revision_id)
    _require(isinstance(deployment, dict) and
             deployment.get("deploymentId") == revision_id and
             deployment.get("namespaceId") == namespace_id and
             deployment.get("agentId") == agent_id,
             "Enterprise deployment readback changed")
    if deployment.get("status") in ("queued", "running"):
        raise Blocked("Enterprise deployment is in progress")
    _require(deployment.get("status") == "succeeded", "Enterprise deployment failed or is unknown")
    agent = api.get(path)
    _require(isinstance(agent, dict) and agent.get("desiredRuntimeState") == "running" and
             agent.get("activeRevisionId") == revision_id,
             "Enterprise Agent is not running the recorded revision")
    return revision_id


def _read_registered(config, api, kube, state):
    """Re-read the inactive tenant identities before any active mutation."""
    namespace_id = state.get("namespaceId")
    configuration_id = state.get("configurationId")
    agent_id = state.get("agentId")
    _require(_valid_resource_id(namespace_id, "ns_") and
             _valid_resource_id(configuration_id, "cfg_") and
             _valid_resource_id(agent_id, "agt_") and
             isinstance(state.get("servicePrincipalId"), str) and
             state.get("configurationGeneration") is not None,
             "Enterprise inactive tenant must be reconciled first")
    kube.tenant_prepared(namespace_id, require_claimed=True)
    discover_exact(api.get("/namespaces"), config["namespace"]["logicalName"], namespace_id,
                   {"existingNamespace": config["namespace"]["existingNamespace"]})
    namespace = api.get("/namespaces/" + namespace_id)
    _require(isinstance(namespace, dict) and namespace.get("id") == namespace_id and
             namespace.get("name") == config["namespace"]["logicalName"] and
             namespace.get("existingNamespace") == config["namespace"]["existingNamespace"] and
             namespace.get("status") == "ready", "Enterprise Namespace readback changed")
    configuration = api.get(f"/namespaces/{namespace_id}/configurations/{configuration_id}")
    _assert_configuration(configuration, namespace_id, configuration_id,
                          desired_configuration(config), state["configurationGeneration"])
    candidates = kube.configuration_candidates(namespace_id)
    _require(len(candidates) == 1, "Configuration ConfigMap set is ambiguous")
    recover_configuration(candidates, configuration, "openclaw-agents")
    agents = api.get(f"/namespaces/{namespace_id}/agents")
    discover_exact(agents, config["agent"]["name"], agent_id,
                   {"configurationId": configuration_id})
    agent = api.get(f"/namespaces/{namespace_id}/agents/{agent_id}")
    _assert_agent(agent, config, namespace_id, configuration_id, agent_id)
    _require(agent.get("servicePrincipalId") == state["servicePrincipalId"],
             "Enterprise Agent principal changed")
    return agent


def reconcile_active(config, api, kube, model_credential):
    """Source-only active path; committed desired state keeps this gate disabled."""
    installation = prove_driver_identity(config, api, kube)
    with ProtectedJournal(config["privateJournal"]["mountPath"],
                          config["source"]["revision"], _identity_hash(config)) as journal:
        state = dict(journal.state)
        _require(state.get("installationId") == installation["installationId"],
                 "journaled Installation identity changed")
        _require(state.get("backup", {}).get("phase") in (None, "complete"),
                 "Enterprise backup transaction is incomplete")
        if config["privateOrigins"]["nativeOrigin"] is not None:
            _require(model_credential["version"] == state.get("modelKeyVersion"),
                     "Enterprise model key version changed without a reviewed rotation")
            reconcile_native_origin_configuration(config, api, kube, journal)
            revision_id = reconcile_native_origin_deployment(config, api, kube, journal)
            state = dict(journal.state)
            return {"namespaceId": state["namespaceId"],
                    "configurationId": state["configurationId"], "agentId": state["agentId"],
                    "revisionId": revision_id, "desiredRuntimeState": "running"}
        _read_registered(config, api, kube, state)
        reconcile_model_secret(config, api, journal, model_credential)
        reconcile_model_grant(api, journal)
        bind_model_secret(config, api, journal)
        ensure_runtime_credentials(api, journal)
        revision_id = reconcile_deployment(config, api, journal)
        state = dict(journal.state)
    return {"namespaceId": state["namespaceId"],
            "configurationId": state["configurationId"], "agentId": state["agentId"],
            "revisionId": revision_id, "desiredRuntimeState": "running"}


def reconcile_native_origin_configuration(config, api, kube, journal):
    """Save the owner-reviewed origin once, without redeploying the first revision.

    A lost PATCH response is recovered only from the exact next generation and
    owned Driver ConfigMap. An unchanged read cannot prove an in-flight PATCH
    will not complete, so it keeps the pending intent and blocks a repost.
    """
    _require(config["privateOrigins"]["nativeOrigin"] is not None,
             "native origin needs an owner-session return")
    before_config = {**config, "privateOrigins": {**config["privateOrigins"],
                                                  "nativeOrigin": None}}
    before_values = desired_configuration(before_config)
    after_values = desired_configuration(config)
    before_hash = hashlib.sha256(json.dumps(before_values, sort_keys=True,
                                             separators=(",", ":")).encode()).hexdigest()
    after_hash = hashlib.sha256(json.dumps(after_values, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
    state = dict(journal.state)
    generation = state.get("configurationGeneration")
    _require(type(generation) is int and 1 <= generation < 9007199254740991 and
             _valid_resource_id(state.get("namespaceId"), "ns_") and
             _valid_resource_id(state.get("agentId"), "agt_") and
             _valid_resource_id(state.get("revisionId"), "rev_") and
             state.get("desiredHash") in (before_hash, after_hash),
             "first Enterprise revision or reviewed Configuration is missing")
    expected_host = hashlib.sha256(
        f"{state['installationId']}\0{state['namespaceId']}\0{state['agentId']}".encode()
    ).hexdigest()[:32]
    _require(config["privateOrigins"]["nativeOrigin"] ==
             f"https://agent-{expected_host}.agents.oce.stinkyboi.com",
             "native origin does not match the returned Agent host")
    pending = state.get("pending")
    if state["desiredHash"] == after_hash:
        _require(generation == 2, "post-origin Configuration generation is invalid")
        _require(pending is None or pending == {
            "operation": "deploy", "baselineRevisionIds": [state["revisionId"]]},
            "journaled Configuration update is incomplete")
        _read_registered(config, api, kube, state)
        return
    _require(generation == 1, "first Enterprise Configuration generation changed")
    _require(pending is None or pending == {"operation": "configuration-update"},
             "another Enterprise operation is pending")
    namespace_id, configuration_id, agent_id = (state["namespaceId"],
                                                state["configurationId"], state["agentId"])
    path = f"/namespaces/{namespace_id}/configurations/{configuration_id}"
    if pending is None:
        # Prove the first revision, grants, deployment, and ownership before
        # changing its saved Configuration. The revision itself stays immutable.
        first = _verify_active_state(before_config, api, kube)
        _require(first["desiredRuntimeState"] == "running",
                 "first Enterprise revision is not running")
        current = api.get(path)
        _assert_configuration(current, namespace_id, configuration_id,
                              before_values, generation)
        state["pending"] = {"operation": "configuration-update"}
        journal.save(state)
        try:
            updated = api.patch(path, configuration_patch(current, after_values, generation))
        except DefinitiveRejection:
            unchanged = api.get(path)
            _assert_configuration(unchanged, namespace_id, configuration_id,
                                  before_values, generation)
            candidates = kube.configuration_candidates(namespace_id)
            _require(len(candidates) == 1, "Configuration ConfigMap set is ambiguous")
            recover_configuration(candidates, unchanged, "openclaw-agents")
            state.pop("pending")
            journal.save(state)
            raise
        _assert_configuration(updated, namespace_id, configuration_id,
                              after_values, generation + 1)
    exact = api.get(path)
    _require(isinstance(exact, dict), "Enterprise Configuration readback changed")
    if exact.get("generation") == generation:
        _assert_configuration(exact, namespace_id, configuration_id,
                              before_values, generation)
        raise Blocked("Configuration update outcome remains unknown; do not retry")
    _assert_configuration(exact, namespace_id, configuration_id,
                          after_values, generation + 1)
    candidates = kube.configuration_candidates(namespace_id)
    _require(len(candidates) == 1, "Configuration ConfigMap set is ambiguous")
    recover_configuration(candidates, exact, "openclaw-agents")
    agent_path = f"/namespaces/{namespace_id}/agents/{agent_id}"
    agent = api.get(agent_path)
    _assert_agent(agent, before_config, namespace_id, configuration_id, agent_id)
    _require(agent.get("servicePrincipalId") == state["servicePrincipalId"] and
             agent.get("desiredRuntimeState") == "running" and
             agent.get("activeRevisionId") == state["revisionId"],
             "first Enterprise revision changed during Configuration update")
    first_revision = api.get(agent_path + "/revisions/" + state["revisionId"])
    _assert_active_revision(first_revision, before_config, state)
    state["configurationGeneration"] = generation + 1
    state["desiredHash"] = after_hash
    state.pop("pending")
    journal.save(state)


def reconcile_native_origin_deployment(config, api, kube, journal):
    """Admit one post-origin revision; never repost an unknown deploy."""
    state = dict(journal.state)
    if state.get("firstRevisionId") is not None:
        current = _verify_active_state(config, api, kube)
        _require(current["desiredRuntimeState"] == "running",
                 "Enterprise post-origin revision is stopped")
        return current["revisionId"]
    first_id = state.get("revisionId")
    _require(_valid_resource_id(first_id, "rev_") and
             type(state.get("configurationGeneration")) is int and
             state["configurationGeneration"] == 2,
             "first Enterprise revision or updated Configuration is missing")
    pending = state.get("pending")
    _require(pending is None or pending == {
        "operation": "deploy", "baselineRevisionIds": [first_id]},
        "another Enterprise operation is pending")
    namespace_id, agent_id = state["namespaceId"], state["agentId"]
    base = f"/namespaces/{namespace_id}/agents/{agent_id}"
    revisions = list_agent_revisions(api, namespace_id, agent_id)
    if pending is None:
        first = _verify_active_state(config, api, kube, allow_transitional=True)
        _require(first["revisionId"] == first_id and
                 first["desiredRuntimeState"] == "running" and
                 len(revisions) == 1 and revisions[0]["id"] == first_id,
                 "first Enterprise revision is not stable")
        agent = api.get(base)
        revision = api.get(base + "/revisions/" + first_id)
        deployment = api.get(base + "/deployments/" + first_id)
        _require(should_deploy(agent, revision, deployment, state["configurationId"],
                               state["configurationGeneration"]),
                 "unchanged Enterprise Configuration must not redeploy")
        latest = list_agent_revisions(api, namespace_id, agent_id)
        _require(len(latest) == 1 and latest[0]["id"] == first_id,
                 "first Enterprise revision changed before deployment")
        state["pending"] = {"operation": "deploy", "baselineRevisionIds": [first_id]}
        journal.save(state)
        try:
            created = api.post_accepted(base + "/deploy")
        except DefinitiveRejection:
            after = list_agent_revisions(api, namespace_id, agent_id)
            exact_agent = api.get(base)
            _require(len(after) == 1 and after[0]["id"] == first_id and
                     exact_agent.get("desiredRuntimeState") == "running" and
                     exact_agent.get("activeRevisionId") == first_id,
                     "deploy outcome changed after rejection")
            state.pop("pending")
            journal.save(state)
            raise

        _require(isinstance(created, dict) and created.get("agentId") == agent_id and
                 created.get("namespaceId") == namespace_id and
                 created.get("configurationId") == state["configurationId"] and
                 created.get("configurationGeneration") == state["configurationGeneration"],
                 "Enterprise post-origin deploy response changed")
        second_id = created.get("id")
    else:
        _require(len(revisions) in (1, 2) and
                 len([item for item in revisions if item["id"] == first_id]) == 1,
                 "post-origin revision history is incomplete or foreign")
        second_id = recover_revision(revisions, {first_id}, agent_id,
                                     state["configurationId"],
                                     state["configurationGeneration"])
    _require(_valid_resource_id(second_id, "rev_") and second_id != first_id,
             "post-origin revision ID is invalid")
    second = api.get(base + "/revisions/" + second_id)
    _assert_active_revision(second, config, {**state, "revisionId": second_id})
    state["firstRevisionId"] = first_id
    state["revisionId"] = second_id
    state.pop("pending")
    journal.save(state)
    current = _verify_active_state(config, api, kube)
    _require(current["desiredRuntimeState"] == "running",
             "Enterprise post-origin revision is not running")
    return second_id


def verify_active(config, api, kube):
    _require(config["privateOrigins"]["nativeOrigin"] is not None,
             "native origin needs an owner-session return and reviewed Configuration update")
    return _verify_active_state(config, api, kube)


def _verify_active_state(config, api, kube, *, allow_transitional=False,
                         allow_backup=False):
    installation = check(config, api, kube)
    path = config["privateJournal"]["mountPath"]
    state, raw = read_journal(path, config["source"]["revision"], _identity_hash(config))
    _require(state.get("installationId") == installation["installationId"] and
             state.get("pending") is None and
             type(state.get("modelKeyVersion")) is int,
             "Enterprise active journal is incomplete")
    _require(state.get("backup", {}).get("phase") in (None, "complete") or
             allow_backup,
             "Enterprise backup transaction is incomplete")
    agent = _read_registered(config, api, kube, state)
    namespace_id, agent_id, secret_id = state["namespaceId"], state["agentId"], state.get("secretId")
    _safe_segment(secret_id, "model Secret")
    secret = api.get(f"/namespaces/{namespace_id}/secrets/{secret_id}")
    _assert_model_secret(secret, namespace_id, secret_id, state.get("secretName"), agent_id)
    _unique_model_secret(api, f"/namespaces/{namespace_id}/secrets", secret_id,
                         state.get("secretName"))
    role_id = _safe_segment(state.get("roleId"), "model Role")
    binding_id = _safe_segment(state.get("bindingId"), "model AccessBinding")
    role_path = f"/namespaces/{namespace_id}/iam/roles"
    binding_path = f"/namespaces/{namespace_id}/iam/access-bindings"
    roles = api.get(role_path)
    bindings = api.get(binding_path)
    _require(isinstance(roles, list) and isinstance(bindings, list) and
             all(isinstance(item, dict) for item in roles + bindings),
             "Enterprise IAM grant lists are invalid")
    _assert_model_role(api.get(role_path + "/" + role_id), namespace_id, role_id,
                       state.get("roleName"))
    _assert_model_binding(api.get(binding_path + "/" + binding_id), namespace_id,
                          binding_id, state["servicePrincipalId"], role_id, secret_id)
    exact_model_grant(roles, bindings, namespace_id, state["servicePrincipalId"], secret_id)
    _require(agent.get("harnessAuth") == _model_auth(namespace_id, secret_id),
             "Enterprise Agent model binding changed")
    status = api.get(f"/namespaces/{namespace_id}/agents/{agent_id}/runtime-credentials")
    _require(status == {"transportConfigured": True},
             "Enterprise runtime credentials are not configured")
    revision_id = state.get("revisionId")
    _require(_valid_resource_id(revision_id, "rev_"), "Enterprise active revision is missing")
    base = f"/namespaces/{namespace_id}/agents/{agent_id}"
    revisions = list_agent_revisions(api, namespace_id, agent_id)
    desired_hash = hashlib.sha256(json.dumps(desired_configuration(config), sort_keys=True,
                                              separators=(",", ":")).encode()).hexdigest()
    _require(state.get("desiredHash") == desired_hash,
             "Enterprise journaled Configuration changed")
    native_origin = config["privateOrigins"]["nativeOrigin"]
    first_id = state.get("firstRevisionId")
    if native_origin is None:
        _require(first_id is None and state.get("revisionIds") is None and
                 len(revisions) == 1 and
                 revisions[0].get("id") == revision_id,
                 "Enterprise revision history changed")
    else:
        _require(type(state["configurationGeneration"]) is int and
                 state["configurationGeneration"] == 2,
                 "post-origin Configuration generation is invalid")
        before_config = {**config, "privateOrigins": {**config["privateOrigins"],
                                                      "nativeOrigin": None}}
        if first_id is None:
            _require(allow_transitional and len(revisions) == 1 and
                     revisions[0].get("id") == revision_id,
                     "post-origin revision is not deployed")
            first_id = revision_id
        else:
            history = state.get("revisionIds", [first_id, revision_id])
            _require(_valid_resource_id(first_id, "rev_") and first_id != revision_id and
                     len(history) >= 2 and history[0] == first_id and
                     history[-1] == revision_id and
                     len(revisions) == len(history) and
                     {item["id"] for item in revisions} == set(history),
                     "Enterprise revision history changed")
        first_state = {**state, "revisionId": first_id,
                       "configurationGeneration": state["configurationGeneration"] - 1}
        _assert_active_revision(api.get(base + "/revisions/" + first_id),
                                before_config, first_state)
        first_deployment = api.get(base + "/deployments/" + first_id)
        _require(isinstance(first_deployment, dict) and
                 first_deployment.get("deploymentId") == first_id and
                 first_deployment.get("namespaceId") == namespace_id and
                 first_deployment.get("agentId") == agent_id and
                 first_deployment.get("status") == "succeeded",
                 "first Enterprise deployment changed")
        if state.get("revisionIds") is not None:
            for historical_id in state["revisionIds"][1:-1]:
                _assert_active_revision(api.get(base + "/revisions/" + historical_id), config,
                                        {**state, "revisionId": historical_id})
                historical_deployment = api.get(base + "/deployments/" + historical_id)
                _require(isinstance(historical_deployment, dict) and
                         historical_deployment.get("deploymentId") == historical_id and
                         historical_deployment.get("namespaceId") == namespace_id and
                         historical_deployment.get("agentId") == agent_id and
                         historical_deployment.get("status") == "succeeded",
                         "historical Enterprise deployment changed")
    if native_origin is None or first_id != revision_id:
        _assert_active_revision(api.get(base + "/revisions/" + revision_id), config, state)
    deployment = api.get(base + "/deployments/" + revision_id)
    _require(isinstance(deployment, dict) and deployment.get("deploymentId") == revision_id and
             deployment.get("namespaceId") == namespace_id and
             deployment.get("agentId") == agent_id and
             deployment.get("status") == "succeeded",
             "Enterprise deployment is not complete")
    if agent.get("desiredRuntimeState") == "running":
        _require(agent.get("activeRevisionId") == revision_id,
                 "Enterprise active revision changed")
    else:
        _require(agent.get("desiredRuntimeState") == "stopped" and
                 agent.get("activeRevisionId") is None,
                 "Enterprise stopped revision changed")
        _assert_stopped_runtime(api, base, revision_id)
        kube.tenant_pods_absent()
    after, second_raw = read_journal(path, config["source"]["revision"], _identity_hash(config))
    _require(raw == second_raw and state == after,
             "Enterprise journal changed during verification")
    return {"namespaceId": namespace_id, "agentId": agent_id,
            "revisionId": revision_id,
            "desiredRuntimeState": agent["desiredRuntimeState"]}


def _assert_stopped_runtime(api, base, revision_id):
    runtime = api.get(base + "/deployments/" + revision_id + "/runtime")
    _require(isinstance(runtime, dict) and runtime.get("revisionId") == revision_id and
             isinstance(runtime.get("observedAt"), str) and
             runtime.get("pods") == [],
             "Enterprise stopped runtime still has Pods or cannot be proved")


def _backup_context(backup, state):
    return {"backupId": backup["id"], "namespaceId": state["namespaceId"],
            "agentId": state["agentId"], "revisionId": backup["sourceRevisionId"]}


def begin_backup_stop(config, api, kube, expected_sha, backup_id):
    """Journal one stop before POST; the caller must reuse its durable backup ID.

    This source-only API has no CLI or workflow entry. A later protected
    coordinator must own the ID and writer fence, and apply the existing
    exact-main and reviewed-config guards before calling it.
    """
    _validate_config(config)
    _require(isinstance(expected_sha, str) and SHA.fullmatch(expected_sha) and
             isinstance(backup_id, str) and HEX64.fullmatch(backup_id),
             "Enterprise backup source or transaction ID is invalid")
    _require(config["activationEnabled"] and
             config["privateOrigins"]["nativeOrigin"] is not None,
             "Enterprise backup needs the reviewed active Agent")
    installation = prove_driver_identity(config, api, kube)
    with ProtectedJournal(config["privateJournal"]["mountPath"],
                          config["source"]["revision"], _identity_hash(config)) as journal:
        state = dict(journal.state)
        _require(state.get("installationId") == installation["installationId"] and
                 state.get("pending") is None,
                 "Enterprise backup journal is incomplete")
        backup = state.get("backup")
        _require(backup is None or backup["id"] == backup_id or
                 backup["phase"] == "complete",
                 "another Enterprise backup transaction is incomplete")
        if backup is not None and backup["id"] == backup_id and backup["phase"] == "complete":
            current = _verify_active_state(config, api, kube)
            _require(current["desiredRuntimeState"] == "running" and
                     current["revisionId"] == backup["resumedRevisionId"],
                     "completed Enterprise backup changed")
            return {**_backup_context(backup, state), "phase": "complete",
                    "revisionId": current["revisionId"]}
        if backup is None or backup["id"] != backup_id:
            current = _verify_active_state(config, api, kube)
            _require(current["desiredRuntimeState"] == "running" and
                     state.get("firstRevisionId") is not None,
                     "Enterprise backup source revision is not running")
            history = state.get("revisionIds", [state["firstRevisionId"],
                                                current["revisionId"]])
            _require(history[-1] == current["revisionId"],
                     "Enterprise backup revision history changed")
            _require(len(history) < 100,
                     "Enterprise backup revision history has no resume headroom")
            state["revisionIds"] = history
            backup = {"id": backup_id, "phase": "stopping",
                      "sourceRevisionId": current["revisionId"],
                      "baselineRevisionIds": list(history)}
            state["backup"] = backup
            journal.save(state)
            base = f"/namespaces/{state['namespaceId']}/agents/{state['agentId']}"
            try:
                accepted = api.post_accepted(base + "/stop")
            except DefinitiveRejection:
                unchanged = _verify_active_state(config, api, kube,
                                                  allow_backup=True)
                _require(unchanged["desiredRuntimeState"] == "running" and
                         unchanged["revisionId"] == backup["sourceRevisionId"],
                         "backup stop outcome changed after rejection")
                state.pop("backup")
                journal.save(state)
                raise
            _require(isinstance(accepted, dict) and accepted.get("id") == state["agentId"] and
                     accepted.get("desiredRuntimeState") == "stopped",
                     "Enterprise backup stop response changed")
        else:
            _require(backup["phase"] in ("stopping", "stopped") and
                     state.get("revisionId") == backup["sourceRevisionId"] and
                     state.get("revisionIds") == backup["baselineRevisionIds"],
                     "Enterprise backup stop state changed")
        current = _verify_active_state(config, api, kube, allow_backup=True)
        _require(current["desiredRuntimeState"] == "stopped" and
                 current["revisionId"] == backup["sourceRevisionId"],
                 "Enterprise backup stop outcome is unknown")
        if backup["phase"] == "stopping":
            backup["phase"] = "stopped"
            state["backup"] = backup
            journal.save(state)
        return {**_backup_context(backup, state), "phase": "stopped"}


def resume_backup(config, api, kube, expected_sha, backup_id, verify_capture):
    """Deploy one new revision only after the caller proves a fenced capture.

    `verify_capture` is a trusted future coordinator callback. It receives the
    exact backup identity and must verify capture, off-node publication, and
    independent restore, returning the verified manifest SHA-256. No deployed
    entrypoint currently calls this source-only method; a later coordinator
    must apply the existing exact-main and reviewed-config guards.
    """
    _validate_config(config)
    _require(isinstance(expected_sha, str) and SHA.fullmatch(expected_sha) and
             isinstance(backup_id, str) and HEX64.fullmatch(backup_id),
             "Enterprise backup source or transaction ID is invalid")
    _require(config["activationEnabled"] and
             config["privateOrigins"]["nativeOrigin"] is not None,
             "Enterprise backup needs the reviewed active Agent")
    installation = prove_driver_identity(config, api, kube)
    with ProtectedJournal(config["privateJournal"]["mountPath"],
                          config["source"]["revision"], _identity_hash(config)) as journal:
        state = dict(journal.state)
        backup = state.get("backup")
        _require(state.get("installationId") == installation["installationId"] and
                 state.get("pending") is None and backup is not None and
                 backup["id"] == backup_id,
                 "Enterprise backup transaction is missing or changed")
        if backup["phase"] == "complete":
            current = _verify_active_state(config, api, kube)
            _require(current["desiredRuntimeState"] == "running" and
                     current["revisionId"] == backup["resumedRevisionId"],
                     "completed Enterprise backup changed")
            return current
        _require(backup["phase"] in ("stopped", "resuming") and
                 state.get("revisionId") == backup["sourceRevisionId"] and
                 state.get("revisionIds") == backup["baselineRevisionIds"],
                 "Enterprise backup stop has not completed")
        if backup["phase"] == "stopped":
            current = _verify_active_state(config, api, kube, allow_backup=True)
            _require(current["desiredRuntimeState"] == "stopped" and
                     current["revisionId"] == backup["sourceRevisionId"],
                     "Enterprise backup stop proof changed")
        _require(callable(verify_capture), "Enterprise backup capture proof is missing")
        capture_digest = verify_capture(_backup_context(backup, state))
        _require(isinstance(capture_digest, str) and HEX64.fullmatch(capture_digest),
                 "Enterprise backup capture proof is invalid")
        _require(backup.get("captureDigest", capture_digest) == capture_digest,
                 "Enterprise backup capture proof changed")
        namespace_id, agent_id = state["namespaceId"], state["agentId"]
        base = f"/namespaces/{namespace_id}/agents/{agent_id}"
        if backup["phase"] == "stopped":
            backup["phase"] = "resuming"
            backup["captureDigest"] = capture_digest
            state["backup"] = backup
            journal.save(state)
            try:
                created = api.post_accepted(base + "/deploy")
            except DefinitiveRejection:
                unchanged = _verify_active_state(config, api, kube,
                                                  allow_backup=True)
                _require(unchanged["desiredRuntimeState"] == "stopped" and
                         unchanged["revisionId"] == backup["sourceRevisionId"],
                         "backup deploy outcome changed after rejection")
                backup = {key: value for key, value in backup.items()
                          if key != "captureDigest"}
                backup["phase"] = "stopped"
                state["backup"] = backup
                journal.save(state)
                raise
            _require(isinstance(created, dict) and
                     created.get("namespaceId") == namespace_id and
                     created.get("agentId") == agent_id and
                     created.get("configurationId") == state["configurationId"] and
                     created.get("configurationGeneration") == state["configurationGeneration"],
                     "Enterprise backup deploy response changed")
            response_id = created.get("id")
        else:
            response_id = None
        _read_registered(config, api, kube, state)
        revisions = list_agent_revisions(api, namespace_id, agent_id)
        candidate_id = recover_revision(revisions, set(backup["baselineRevisionIds"]),
                                        agent_id, state["configurationId"],
                                        state["configurationGeneration"])
        _require(response_id is None or response_id == candidate_id,
                 "Enterprise backup deploy response differs from revision history")
        _require(len(revisions) == len(backup["baselineRevisionIds"]) + 1 and
                 set(backup["baselineRevisionIds"]).issubset({item["id"] for item in revisions}),
                 "Enterprise backup revision history changed")
        revision = api.get(base + "/revisions/" + candidate_id)
        _assert_active_revision(revision, config, {**state, "revisionId": candidate_id})
        deployment = api.get(base + "/deployments/" + candidate_id)
        _require(isinstance(deployment, dict) and
                 deployment.get("deploymentId") == candidate_id and
                 deployment.get("namespaceId") == namespace_id and
                 deployment.get("agentId") == agent_id and
                 deployment.get("status") == "succeeded",
                 "Enterprise backup deployment is not complete")
        agent = api.get(base)
        _assert_agent(agent, config, namespace_id, state["configurationId"], agent_id)
        _require(agent.get("servicePrincipalId") == state["servicePrincipalId"] and
                 agent.get("harnessAuth") == _model_auth(namespace_id, state["secretId"]) and
                 agent.get("desiredRuntimeState") == "running" and
                 agent.get("activeRevisionId") == candidate_id,
                 "Enterprise backup active revision changed")
        state["revisionId"] = candidate_id
        state["revisionIds"] = backup["baselineRevisionIds"] + [candidate_id]
        backup["phase"] = "complete"
        backup["resumedRevisionId"] = candidate_id
        state["backup"] = backup
        journal.save(state)
        return _verify_active_state(config, api, kube)


def stop_agent(config, api, kube, expected_sha):
    """Request native stop once, then wait for exact revision termination."""
    _validate_config(config)
    _require(isinstance(expected_sha, str) and SHA.fullmatch(expected_sha),
             "Expected repository SHA is invalid")
    installation = prove_driver_identity(config, api, kube)
    with ProtectedJournal(config["privateJournal"]["mountPath"],
                          config["source"]["revision"], _identity_hash(config)) as journal:
        state = dict(journal.state)
        _require(state.get("installationId") == installation["installationId"],
                 "journaled Installation identity changed")
        _require(state.get("backup", {}).get("phase") in (None, "complete"),
                 "Enterprise backup transaction is incomplete")
        agent = _read_registered(config, api, kube, state)
        pending = state.get("pending")
        _require(pending is None or pending == {"operation": "stop"},
                 "another Enterprise operation is pending")
        revision_id = state.get("revisionId")
        base = f"/namespaces/{state['namespaceId']}/agents/{state['agentId']}"
        if revision_id is None:
            raise Blocked("stop requires a journaled revision; inactive Agent state is unproven")
        _require(_valid_resource_id(revision_id, "rev_"),
                 "Enterprise revision ID is invalid")
        if pending is None and not (agent.get("desiredRuntimeState") == "stopped" and
                                    agent.get("activeRevisionId") is None):
            _require(agent.get("desiredRuntimeState") == "running" and
                     agent.get("activeRevisionId") in (None, revision_id),
                     "Enterprise Agent active revision changed")
            state["pending"] = {"operation": "stop"}
            journal.save(state)
            try:
                accepted = api.post_accepted(base + "/stop")
            except DefinitiveRejection:
                after = api.get(base)
                _assert_agent(after, config, state["namespaceId"],
                              state["configurationId"], state["agentId"])
                _require(after.get("servicePrincipalId") == state["servicePrincipalId"] and
                         after.get("desiredRuntimeState") == agent.get("desiredRuntimeState") and
                         after.get("activeRevisionId") == agent.get("activeRevisionId"),
                         "stop outcome changed after rejection")
                state.pop("pending")
                journal.save(state)
                raise
            _require(isinstance(accepted, dict) and accepted.get("id") == state["agentId"] and
                     accepted.get("desiredRuntimeState") == "stopped",
                     "Enterprise stop response changed")
        agent = api.get(base)
        _assert_agent(agent, config, state["namespaceId"], state["configurationId"],
                      state["agentId"])
        _require(agent.get("servicePrincipalId") == state["servicePrincipalId"] and
                 agent.get("desiredRuntimeState") == "stopped",
                 "Enterprise stop outcome is unknown")
        _require(agent.get("activeRevisionId") is None,
                 "Enterprise stop is still in progress")
        _assert_stopped_runtime(api, base, revision_id)
        kube.tenant_pods_absent()
        if state.get("pending") is not None:
            state.pop("pending")
            journal.save(state)
        return {"agentId": state["agentId"], "revisionId": revision_id,
                "desiredRuntimeState": "stopped"}


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
    if (not isinstance(origins, dict) or origins.get("console") != CONSOLE_ORIGIN or
            "nativeOrigin" not in origins):
        raise Blocked("Enterprise console origin changed")
    native_origin = origins.get("nativeOrigin")
    if native_origin is not None and (not isinstance(native_origin, str) or not re.fullmatch(
            r"https://agent-[0-9a-f]{32}\.agents\.oce\.stinkyboi\.com", native_origin)):
        raise Blocked("Enterprise native origin is not a reviewed returned origin")
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
            not isinstance(deployment, dict) or type(generation) is not int or
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
    if (type(active_generation) is not int or active_generation < 1 or
            generation < active_generation):
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

    def __init__(self, path, source_sha, config_sha, *, create_lock=True):
        self.path = Path(path)
        self.source_sha = source_sha
        self.config_sha = config_sha
        self.create_lock = create_lock
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
        if not self.create_lock:
            _require(self.path.is_file(), "Enterprise journal is missing")
            _require(lock_path.is_file(), "Journal lock is missing")
        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        if self.create_lock:
            flags |= os.O_CREAT
        self.lock_fd = os.open(lock_path, flags, 0o600)
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
            if field in ("pending", "revisionIds", "backup"):
                continue
            if field in ("configurationGeneration", "modelKeyVersion"):
                if type(value) is not int or not 1 <= value <= 9007199254740991:
                    raise Blocked("Journal generation or credential version is invalid")
            elif field == "desiredHash":
                if not isinstance(value, str) or not HEX64.fullmatch(value):
                    raise Blocked("Journal desired hash is invalid")
            elif (not isinstance(value, str) or not 1 <= len(value) <= 200 or
                  not re.fullmatch(r"[A-Za-z0-9._~:@/-]+", value) or
                  (field in ID_PREFIXES and
                   not _valid_resource_id(value, ID_PREFIXES[field]))):
                raise Blocked("Journal resource identity is invalid")
        history = state.get("revisionIds")
        if "revisionIds" in state and history is None:
            raise Blocked("Journal revision history is invalid")
        if history is not None and (not isinstance(history, list) or
                                    not 2 <= len(history) <= 100 or
                                    any(not _valid_resource_id(item, "rev_") for item in history) or
                                    len(set(history)) != len(history)):
            raise Blocked("Journal revision history is invalid")
        backup = state.get("backup")
        if "backup" in state and backup is None:
            raise Blocked("Journal backup transaction is invalid")
        if backup is not None:
            if (not isinstance(backup, dict) or
                    set(backup) - {"id", "phase", "sourceRevisionId", "baselineRevisionIds",
                                   "captureDigest", "resumedRevisionId"} or
                    not isinstance(backup.get("id"), str) or
                    not HEX64.fullmatch(backup["id"]) or
                    backup.get("phase") not in ("stopping", "stopped", "resuming", "complete") or
                    not _valid_resource_id(backup.get("sourceRevisionId"), "rev_") or
                    not isinstance(backup.get("baselineRevisionIds"), list) or
                    not 2 <= len(backup["baselineRevisionIds"]) <= 100 or
                    history is None or backup["baselineRevisionIds"] !=
                    history[:len(backup["baselineRevisionIds"])] or
                    backup["baselineRevisionIds"][-1] != backup["sourceRevisionId"]):
                raise Blocked("Journal backup transaction is invalid")
            phase = backup["phase"]
            if phase in ("stopping", "stopped"):
                if set(backup) != {"id", "phase", "sourceRevisionId", "baselineRevisionIds"}:
                    raise Blocked("Journal backup transaction is invalid")
            elif phase == "resuming":
                if (set(backup) != {"id", "phase", "sourceRevisionId",
                                    "baselineRevisionIds", "captureDigest"} or
                        not isinstance(backup["captureDigest"], str) or
                        not HEX64.fullmatch(backup["captureDigest"])):
                    raise Blocked("Journal backup capture digest is invalid")
            elif (set(backup) != {"id", "phase", "sourceRevisionId",
                                  "baselineRevisionIds", "captureDigest", "resumedRevisionId"} or
                  not isinstance(backup["captureDigest"], str) or
                  not HEX64.fullmatch(backup["captureDigest"]) or
                  not _valid_resource_id(backup["resumedRevisionId"], "rev_") or
                  history[-1] != backup["resumedRevisionId"] or
                  len(history) != len(backup["baselineRevisionIds"]) + 1):
                raise Blocked("Journal completed backup is invalid")
        pending = state.get("pending")
        if pending is not None:
            if (not isinstance(pending, dict) or
                    set(pending) - {"operation", "baselineRevisionIds",
                                    "baselineConfigmapUids", "baselineAgentIds",
                                    "baselineSecretIds", "baselineRoleIds",
                                    "baselineBindingIds"} or
                    pending.get("operation") not in ("namespace-create", "configuration-create",
                                                     "agent-create", "secret-create",
                                                     "role-create", "binding-create",
                                                     "agent-bind", "runtime-credentials",
                                                     "deploy", "stop", "configuration-update") or
                    not isinstance(pending.get("baselineRevisionIds", []), list) or
                    any(not isinstance(item, str) or not item.startswith("rev_") or
                        not re.fullmatch(r"[A-Za-z0-9._~:@/-]{1,200}", item)
                        for item in pending.get("baselineRevisionIds", [])) or
                    any(not isinstance(pending.get(key, []), list) or
                        any(not isinstance(item, str) or not re.fullmatch(
                            r"[A-Za-z0-9._~:@/-]{1,200}", item)
                            for item in pending.get(key, []))
                        for key in ("baselineConfigmapUids", "baselineAgentIds",
                                    "baselineSecretIds", "baselineRoleIds",
                                    "baselineBindingIds"))):
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


def _read_model_credential(path, expected_parameter):
    """Read an SSM-versioned provider key without exposing its value or digest."""
    candidate = Path(path)
    if not candidate.is_absolute() or candidate.parent.resolve() != candidate.parent:
        raise Blocked("Enterprise model credential path is not private")
    parent = candidate.parent
    if not parent.is_dir() or parent.stat().st_uid != os.getuid() or stat.S_IMODE(
            parent.stat().st_mode) != 0o700:
        raise Blocked("Enterprise model credential parent is not private")
    ProtectedJournal._check_file(candidate)
    if not candidate.is_file() or candidate.stat().st_size > 70000:
        raise Blocked("Enterprise model credential file is missing or oversized")
    try:
        document = json.loads(candidate.read_text())
    except (OSError, UnicodeError, ValueError):
        raise Blocked("Enterprise model credential file is invalid") from None
    _require(isinstance(document, dict) and set(document) == {"parameter", "version", "key"} and
             document["parameter"] == expected_parameter and
             type(document["version"]) is int and 1 <= document["version"] <= 9007199254740991 and
             isinstance(document["key"], str) and document["key"] == document["key"].strip() and
             bool(document["key"]) and not any(char in document["key"]
                                                for char in ("\x00", "\r", "\n")) and
             len(document["key"].encode("utf-8")) <= 65536,
             "Enterprise model credential contract is invalid")
    return {"version": document["version"], "key": document["key"]}


def _require_reviewed_mutation_config(path, expected_sha):
    """A caller cannot flip the inactive switch with a local config override."""
    canonical = ROOT / "scripts/config/openclaw-enterprise.json"
    _require(Path(path).resolve() == canonical.resolve(),
             "Enterprise mutation config path is not repository-owned")
    try:
        committed = subprocess.check_output(
            ["git", "show", expected_sha + ":scripts/config/openclaw-enterprise.json"],
            cwd=ROOT)
    except (OSError, subprocess.CalledProcessError):
        raise Blocked("Enterprise reviewed mutation config is unavailable") from None
    _require(canonical.read_bytes() == committed,
             "Enterprise mutation config differs from exact reviewed commit")


def _require_operator_image_source(source_sha):
    try:
        actual = (ROOT / "operator-source.sha").read_text().strip()
    except OSError:
        raise Blocked("Enterprise operator image source is unavailable") from None
    _require(actual == source_sha, "Enterprise operator image source changed")


def _require_projected_operator_config(path, expected_sha, source_sha, config_sha):
    """Check the current-main config projected by the protected Job dispatcher.

    The immutable ConfigMap is created from the exact main checkout. The image
    contains an earlier reviewed source commit, so its Git history cannot
    contain the later commit that pins the image digest.
    """
    _require(SHA.fullmatch(expected_sha) and SHA.fullmatch(source_sha) and
             HEX64.fullmatch(config_sha), "Enterprise operator source identity is invalid")
    _require(Path(path) == Path("/etc/oce-operator-config/openclaw-enterprise.json"),
             "Enterprise operator config path changed")
    _require_operator_image_source(source_sha)
    _require(hashlib.sha256(Path(path).read_bytes()).hexdigest() == config_sha,
             "Enterprise projected config digest changed")
    try:
        receipt = json.loads(Path(path).with_name("receipt.json").read_text())
    except (OSError, ValueError):
        raise Blocked("Enterprise projected source receipt is unavailable") from None
    _require(receipt == {"expectedSha": expected_sha, "imageSourceSha": source_sha,
                         "configSha256": config_sha},
             "Enterprise projected source receipt changed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "reconcile", "verify", "stop"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--expected-sha")
    parser.add_argument("--operator-source-sha")
    parser.add_argument("--reviewed-config-sha256")
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--model-credential-file", type=Path)
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text())
        _validate_config(config)
        operator_mode = (args.operator_source_sha is not None or
                         args.reviewed_config_sha256 is not None)
        if operator_mode:
            _require(args.expected_sha is not None and
                     args.operator_source_sha is not None and
                     args.reviewed_config_sha256 is not None,
                     "Enterprise operator source receipt is incomplete")
            _require_projected_operator_config(args.config, args.expected_sha,
                                               args.operator_source_sha,
                                               args.reviewed_config_sha256)
            _require(config.get("journalOperator", {}).get("imageSourceSha") ==
                     args.operator_source_sha,
                     "Enterprise operator source declaration changed")
        if args.command in ("reconcile", "stop"):
            if args.expected_sha is None or args.credential_file is None:
                raise Blocked("mutation requires expected SHA and mounted credential file")
            if not operator_mode:
                actual = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
                if actual != args.expected_sha:
                    raise Blocked("Enterprise mutation source SHA is not exact")
                _require_reviewed_mutation_config(args.config, actual)
            key_path = args.credential_file
        else:
            key_path = Path(config["bootstrap"]["serviceKeyFile"])
        api = API(config["privateOrigins"]["console"], _read_key(key_path))
        kube = Kubernetes()
        if args.command == "reconcile":
            model_credential = None
            if config["activationEnabled"]:
                if args.model_credential_file is None:
                    raise Blocked("active reconciliation requires model credential file")
                model_credential = _read_model_credential(
                    args.model_credential_file, config["secrets"]["modelApiKey"])
                _require(model_credential["key"] != api.key,
                         "model key must be distinct from bootstrap service key")
            reconcile(config, api, kube, args.expected_sha, model_credential)
        elif args.command == "stop":
            stop_agent(config, api, kube, args.expected_sha)
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
