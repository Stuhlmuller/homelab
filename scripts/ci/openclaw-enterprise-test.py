#!/usr/bin/env python3
"""Offline failure fixtures for the pinned Enterprise API contract."""

import base64
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("oce_reconciler", ROOT / "scripts/openclaw-enterprise.py")
OCE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = OCE
SPEC.loader.exec_module(OCE)


class FakeAPI:
    def __init__(self, reads):
        self.reads = reads
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path))
        return self.reads[path]

    def post(self, path, body):
        self.calls.append(("POST", path, body))
        raise AssertionError("offline fixture must not mutate")

    def patch(self, path, body):
        self.calls.append(("PATCH", path, body))
        raise AssertionError("offline fixture must not mutate")


class FakeKubernetes:
    def __init__(self, snapshots):
        self.snapshots = iter(snapshots)
        self.calls = []

    def snapshot(self, digest):
        self.calls.append(digest)
        return next(self.snapshots)

    def tenant_prepared(self, namespace_id=None, require_claimed=False):
        self.calls.append(("tenant-prepared", namespace_id, require_claimed))


class NamespaceAPI:
    def __init__(self, existing=None, lost_response=False):
        self.namespaces = list(existing or [])
        self.lost_response = lost_response
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path))
        if path == "/installation":
            return {"id": "ins_one"}
        if path == "/namespaces":
            return copy.deepcopy(self.namespaces)
        for item in self.namespaces:
            if path == "/namespaces/" + item["id"]:
                return copy.deepcopy(item)
        raise AssertionError("unexpected API path: " + path)

    def post(self, path, body):
        self.calls.append(("POST", path, copy.deepcopy(body)))
        if path != "/namespaces":
            raise AssertionError("unexpected mutation: " + path)
        item = {"id": "ns_one", "name": body["name"],
                "existingNamespace": body["existingNamespace"], "status": "ready"}
        self.namespaces.append(item)
        if self.lost_response:
            raise OCE.Blocked("Enterprise API request failed or returned invalid JSON")
        return copy.deepcopy(item)


class TenantAPI:
    """Small pinned-shape store; mutation failures happen after persistence."""

    def __init__(self):
        self.namespace = {"id": "ns_one", "name": "claw",
                          "existingNamespace": "openclaw-agents", "status": "ready"}
        self.configurations = {}
        self.agents = {}
        self.calls = []
        self.lose = None

    def get(self, path):
        self.calls.append(("GET", path))
        if path == "/namespaces":
            return [copy.deepcopy(self.namespace)]
        if path == "/namespaces/ns_one":
            return copy.deepcopy(self.namespace)
        if path == "/namespaces/ns_one/agents":
            return [copy.deepcopy(item) for item in self.agents.values()]
        if path.startswith("/namespaces/ns_one/configurations/"):
            return copy.deepcopy(self.configurations[path.rsplit("/", 1)[-1]])
        if path.startswith("/namespaces/ns_one/agents/"):
            return copy.deepcopy(self.agents[path.rsplit("/", 1)[-1]])
        raise AssertionError("unexpected API path: " + path)

    def post(self, path, body):
        self.calls.append(("POST", path, copy.deepcopy(body)))
        if path == "/namespaces/ns_one/configurations":
            item = {"id": "cfg_one", "namespaceId": "ns_one", "kind": "agent",
                    "createdAt": "2026-10-19T00:00:00.000Z", "generation": 1,
                    "values": copy.deepcopy(body["values"])}
            self.configurations[item["id"]] = item
            operation = "configuration"
        elif path == "/namespaces/ns_one/agents":
            item = {"id": "agt_one", "namespaceId": "ns_one", "name": body["name"],
                    "configurationId": body["configurationId"], "executionMode": "embedded",
                    "backendId": None, "status": "active", "desiredRuntimeState": "stopped",
                    "activeRevisionId": None, "harnessAuth": None,
                    "servicePrincipalId": "sp_one"}
            self.agents[item["id"]] = item
            operation = "agent"
        else:
            raise AssertionError("unexpected mutation: " + path)
        if self.lose == operation:
            self.lose = None
            raise OCE.Blocked("Enterprise API request failed or returned invalid JSON")
        return copy.deepcopy(item)


class ActiveTenantAPI(TenantAPI):
    """Pinned metadata shapes; model material is never returned by OCC reads."""

    def __init__(self):
        super().__init__()
        self.secrets = {}
        self.roles = {}
        self.bindings = {}
        self.transport_configured = False
        self.revisions = {}
        self.deployments = {}
        self.runtime_pods = []

    def get(self, path):
        self.calls.append(("GET", path))
        if path == "/namespaces/ns_one/secrets":
            return [{key: copy.deepcopy(item[key]) for key in ("id", "name", "namespaceId", "ref")}
                    for item in self.secrets.values()]
        if path.startswith("/namespaces/ns_one/secrets/"):
            item = copy.deepcopy(self.secrets[path.rsplit("/", 1)[-1]])
            consumers = {"agents": [], "configurations": [], "credentialSources": [],
                         "provisioningRequests": [], "truncated": False, "unreadable": 0}
            for agent in self.agents.values():
                if (agent.get("harnessAuth") or {}).get("source", {}).get("id") == item["id"]:
                    consumers["agents"].append(agent["id"])
            item["consumers"] = consumers
            return item
        if path == "/namespaces/ns_one/iam/roles":
            return copy.deepcopy(list(self.roles.values()))
        if path.startswith("/namespaces/ns_one/iam/roles/"):
            return copy.deepcopy(self.roles[path.rsplit("/", 1)[-1]])
        if path == "/namespaces/ns_one/iam/access-bindings":
            return copy.deepcopy(list(self.bindings.values()))
        if path.startswith("/namespaces/ns_one/iam/access-bindings/"):
            return copy.deepcopy(self.bindings[path.rsplit("/", 1)[-1]])
        if path == "/namespaces/ns_one/agents/agt_one/runtime-credentials":
            return {"transportConfigured": self.transport_configured}
        if path.startswith("/namespaces/ns_one/agents/agt_one/revisions/"):
            return copy.deepcopy(self.revisions[path.rsplit("/", 1)[-1]])
        if path.startswith("/namespaces/ns_one/agents/agt_one/deployments/"):
            parts = path.split("/")
            revision_id = parts[6]
            if len(parts) == 8 and parts[-1] == "runtime":
                return {"revisionId": revision_id, "observedAt": "2026-10-19T00:00:00.000Z",
                        "pods": copy.deepcopy(self.runtime_pods)}
            return copy.deepcopy(self.deployments[revision_id])
        return super().get(path)

    def post(self, path, body):
        if path == "/namespaces/ns_one/secrets":
            self.calls.append(("POST", path, {"name": body["name"], "value": "[redacted]"}))
            item = {"id": "sec_one", "name": body["name"], "namespaceId": "ns_one",
                    "ref": {"kind": "secret", "namespaceId": "ns_one", "id": "sec_one"}}
            self.secrets[item["id"]] = item
            if self.lose == "secret":
                self.lose = None
                raise OCE.Blocked("lost Secret response")
            return copy.deepcopy(item)
        if path == "/namespaces/ns_one/iam/roles":
            self.calls.append(("POST", path, copy.deepcopy(body)))
            item = {"id": "role_one", "name": body["name"],
                    "namespaceId": "ns_one", "permissions": copy.deepcopy(body["permissions"])}
            self.roles[item["id"]] = item
            if self.lose == "role":
                self.lose = None
                raise OCE.Blocked("lost Role response")
            return copy.deepcopy(item)
        if path == "/namespaces/ns_one/iam/access-bindings":
            self.calls.append(("POST", path, copy.deepcopy(body)))
            item = {"id": "binding_one", "namespaceId": "ns_one", **body}
            self.bindings[item["id"]] = item
            if self.lose == "binding":
                self.lose = None
                raise OCE.Blocked("lost Binding response")
            return copy.deepcopy(item)
        return super().post(path, body)

    def patch(self, path, body):
        self.calls.append(("PATCH", path, copy.deepcopy(body)))
        if path == "/namespaces/ns_one/configurations/cfg_one":
            item = self.configurations["cfg_one"]
            if body.get("expectedGeneration") != item["generation"]:
                raise OCE.Blocked("HTTP 409")
            item["generation"] += 1
            item["values"] = copy.deepcopy(body["values"])
            if self.lose == "configuration-update":
                self.lose = None
                raise OCE.Blocked("lost Configuration update response")
            return copy.deepcopy(item)
        if path != "/namespaces/ns_one/agents/agt_one":
            raise AssertionError("unexpected PATCH")
        self.agents["agt_one"]["harnessAuth"] = copy.deepcopy(body["harnessAuth"])
        if self.lose == "agent-bind":
            self.lose = None
            raise OCE.Blocked("lost Agent binding response")
        return copy.deepcopy(self.agents["agt_one"])

    def post_ok(self, path, body):
        self.calls.append(("POST-200", path, copy.deepcopy(body)))
        if path != "/namespaces/ns_one/agents/agt_one/runtime-credentials":
            raise AssertionError("unexpected POST 200")
        self.transport_configured = True
        if self.lose == "runtime-credentials":
            self.lose = None
            raise OCE.Blocked("lost runtime credential response")
        return {"transportConfigured": True}

    def post_accepted(self, path, body=None):
        self.calls.append(("POST-202", path, copy.deepcopy(body)))
        if path == "/namespaces/ns_one/agents/agt_one/deploy":
            agent = self.agents["agt_one"]
            generation = self.configurations["cfg_one"]["generation"]
            if generation not in (1, 2):
                raise AssertionError("unexpected Configuration generation")
            revision_id = "rev_one" if generation == 1 else "rev_two"
            if revision_id in self.revisions:
                raise AssertionError("unchanged Configuration was redeployed")
            # Pinned OCC admits platform logging when Kubernetes Compute owns
            # the runtime and the Installation omits a logging override.
            admitted = copy.deepcopy(self.configurations["cfg_one"]["values"])
            admitted["logging"] = {"level": "info", "consoleLevel": "info",
                                   "consoleStyle": "json"}
            admitted["diagnostics"] = {"otel": {"logs": False}}
            item = {"id": revision_id, "namespaceId": "ns_one", "agentId": "agt_one",
                    "configurationId": "cfg_one", "configurationGeneration": generation,
                    "configurationKind": "agent", "backendId": None,
                    "configuration": admitted,
                    "harnessAuth": copy.deepcopy(agent["harnessAuth"]),
                    "harness": {"id": "openclaw", "mode": "embedded", "version": "1"}}
            self.revisions[item["id"]] = item
            self.deployments[item["id"]] = {"deploymentId": item["id"],
                                            "namespaceId": "ns_one", "agentId": "agt_one",
                                            "status": "succeeded"}
            agent["desiredRuntimeState"] = "running"
            agent["activeRevisionId"] = item["id"]
            self.runtime_pods = [{"name": "agent-one"}]
            if self.lose == "deploy":
                self.lose = None
                raise OCE.Blocked("lost deploy response")
            return copy.deepcopy(item)
        if path == "/namespaces/ns_one/agents/agt_one/stop":
            agent = self.agents["agt_one"]
            agent["desiredRuntimeState"] = "stopped"
            agent["activeRevisionId"] = None
            self.runtime_pods = []
            if self.lose == "stop":
                self.lose = None
                raise OCE.Blocked("lost stop response")
            return copy.deepcopy(agent)
        raise AssertionError("unexpected POST 202")

    def revisions_page(self, path, cursor=None):
        self.calls.append(("GET-PAGE", path, cursor))
        if path != "/namespaces/ns_one/agents/agt_one/revisions":
            raise AssertionError("unexpected revision page")
        return {"data": copy.deepcopy(list(self.revisions.values())),
                "meta": {"nextCursor": None}}


class TenantKubernetes:
    def __init__(self, api):
        self.api = api
        self.calls = []
        self.tenant_pods = []

    def tenant_prepared(self, namespace_id=None, require_claimed=False):
        self.calls.append(("tenant-prepared", namespace_id, require_claimed))

    def tenant_pods_absent(self):
        self.calls.append(("tenant-pods-absent",))
        if self.tenant_pods:
            raise OCE.Blocked("Enterprise tenant still has Pods")

    def configuration_candidates(self, namespace_id):
        self.calls.append(("configuration-candidates", namespace_id))
        result = []
        for item in self.api.configurations.values():
            configuration_id = item["id"]
            result.append({"metadata": {
                "uid": "kube-" + configuration_id,
                "name": OCE.configuration_configmap_name(configuration_id),
                "namespace": "openclaw-agents",
                "labels": {"app.kubernetes.io/managed-by": "openclaw-enterprise",
                           "openclaw.dev/namespace": namespace_id,
                           "openclaw.dev/configuration": configuration_id},
                "annotations": {"openclaw.dev/namespace-id": namespace_id,
                                "openclaw.dev/configuration-id": configuration_id,
                                "openclaw.dev/configuration-kind": "agent",
                                "openclaw.dev/configuration-generation": str(item["generation"]),
                                "openclaw.dev/configuration-created-at": item["createdAt"]}},
                "data": {"openclaw.json": json.dumps(item["values"])}})
        return result


class EnterpriseReconciliation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oce-reconciler-")
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name).resolve() / "private"
        self.private.mkdir(mode=0o700)
        self.config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        self.config["privateJournal"]["mountPath"] = str(self.private / "journal.json")

    def test_installation_read_cannot_prove_selected_drivers(self):
        installation = {"id": "ins_one", "name": "oce", "createdAt": "2026-10-18T00:00:00Z",
                        "capabilities": {"openclaw": {"executionModes": ["embedded"]}}}
        with self.assertRaisesRegex(OCE.Blocked, "selected Drivers"):
            OCE.require_driver_identity(installation)

    def test_service_key_rejects_header_injection(self):
        with self.assertRaisesRegex(OCE.Blocked, "service key is invalid"):
            OCE.API("https://console.oce.stinkyboi.com", "test-key\nother-header: injected")

    def test_service_key_destination_is_pinned(self):
        for origin in ("https://unexpected.example", "https://console.oce.stinkyboi.com.evil.example",
                       "https://console.oce.stinkyboi.com:444"):
            with self.subTest(origin=origin), self.assertRaisesRegex(OCE.Blocked, "console origin changed"):
                OCE.API(origin, "test-key")
        changed = copy.deepcopy(self.config)
        changed["privateOrigins"]["console"] = "https://unexpected.example"
        with self.assertRaisesRegex(OCE.Blocked, "console origin changed"):
            OCE._validate_config(changed)

    def test_api_post_uses_pinned_origin_and_hides_failure_body(self):
        api = OCE.API(OCE.CONSOLE_ORIGIN, "private-service-key")

        class Response(io.BytesIO):
            status = 201

        requests = []

        def respond(request, timeout):
            requests.append((request, timeout))
            return Response(b'{"data":{"id":"ns_one"}}')

        with patch.object(api.opener, "open", side_effect=respond):
            self.assertEqual(api.post("/namespaces", {"name": "claw"}), {"id": "ns_one"})
        request, timeout = requests[0]
        self.assertEqual(request.full_url, OCE.CONSOLE_ORIGIN + "/namespaces")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {"name": "claw"})
        self.assertEqual(timeout, 15)
        private_body = b"private-service-key"
        error = HTTPError(OCE.CONSOLE_ORIGIN + "/namespaces", 409, "conflict", {}, io.BytesIO(private_body))
        self.addCleanup(error.close)
        with patch.object(api.opener, "open", side_effect=error):
            with self.assertRaisesRegex(OCE.Blocked, "HTTP 409") as raised:
                api.post("/namespaces", {"name": "claw"})
        self.assertNotIn(private_body.decode(), str(raised.exception))
        denied = HTTPError(OCE.CONSOLE_ORIGIN + "/namespaces", 403, "forbidden", {},
                           io.BytesIO(private_body))
        self.addCleanup(denied.close)
        with patch.object(api.opener, "open", side_effect=denied):
            with self.assertRaisesRegex(OCE.DefinitiveRejection, "HTTP 403") as raised:
                api.post("/namespaces", {"name": "claw"})
        self.assertNotIn(private_body.decode(), str(raised.exception))

    def test_reviewed_installation_must_match_chart_secret_checksum_and_image(self):
        candidate = (ROOT / "clusters/homelab/apps/openclaw-enterprise/installation.yaml").read_bytes()
        digest = hashlib.sha256(candidate).hexdigest()
        controller = self.config["source"]["images"]["controller"]
        image = controller["repository"] + "@" + controller["digest"]
        values = {"installation": {"secretName": "occ-installation-startup-" + digest[:32],
                                    "key": "installation.yaml"},
                  "controlPlane": {"installationChecksum": digest},
                  "images": {"controller": image}}
        with patch.object(OCE.subprocess, "check_output", return_value=json.dumps(values)):
            self.assertEqual(OCE.reviewed_installation(self.config), (candidate, digest, image))
            values["controlPlane"]["installationChecksum"] = "0" * 64
            with patch.object(OCE.subprocess, "check_output", return_value=json.dumps(values)):
                with self.assertRaisesRegex(OCE.Blocked, "binding changed"):
                    OCE.reviewed_installation(self.config)

    def _installation_snapshot(self):
        document = b"occ:\n  cluster: fixture\ndrivers:\n  compute:\n    id: kubernetes\n"
        digest = hashlib.sha256(document).hexdigest()
        secret_name = "occ-installation-startup-" + digest[:32]
        self.assertLessEqual(len(secret_name), 63)
        image = "harbor.example/controller@sha256:" + "a" * 64
        secret = {
            "metadata": {"name": secret_name, "namespace": "openclaw-system",
                         "uid": "secret-one", "resourceVersion": "100",
                         "creationTimestamp": "2026-10-18T00:00:00Z",
                         "annotations": {"openclaw.dev/installation-id": "ins_one"}},
            "immutable": True, "type": "Opaque",
            "data": {"installation.yaml": base64.b64encode(document).decode()},
        }
        deployments, replicasets, pods = {}, {}, {}
        for component in ("api", "worker"):
            name = "openclaw-enterprise-" + component
            labels = {"app.kubernetes.io/instance": "oce",
                      "app.kubernetes.io/component": component}
            pod_spec = {
                "volumes": [{"name": "installation-startup", "secret": {
                    "secretName": secret_name, "items": [{"key": "installation.yaml",
                                                  "path": "installation.yaml"}],
                    "defaultMode": 420}}],
                "containers": [{"name": component, "image": image,
                                "args": ["apps/controller/src/" +
                                         ("server" if component == "api" else "worker") + ".mjs"],
                                "env": [{"name": "OCC_CONFIG_PATH", "value":
                                         "/etc/openclaw/installation/installation.yaml"}],
                                "volumeMounts": [{"name": "installation-startup",
                                                  "mountPath": "/etc/openclaw/installation",
                                                  "readOnly": True}]}],
            }
            template = {"metadata": {"labels": labels, "annotations": {
                "openclaw.dev/installation-checksum": digest}}, "spec": pod_spec}
            deployments[component] = {
                "metadata": {"name": name, "namespace": "openclaw-system",
                             "uid": "dep-" + component, "resourceVersion": "200",
                             "generation": 1, "labels": labels},
                "spec": {"replicas": 1, "template": copy.deepcopy(template)},
                "status": {"observedGeneration": 1, "replicas": 1,
                           "updatedReplicas": 1, "availableReplicas": 1},
            }
            replicasets[component] = [{
                "metadata": {"name": "rs-" + component, "uid": "rs-" + component,
                             "namespace": "openclaw-system",
                             "resourceVersion": "300",
                             "ownerReferences": [{"kind": "Deployment", "controller": True,
                                                  "uid": "dep-" + component, "name": name}]},
                "spec": {"template": copy.deepcopy(template)},
            }]
            pods[component] = [{
                "metadata": {"name": "pod-" + component, "uid": "pod-" + component,
                             "resourceVersion": "400",
                             "namespace": "openclaw-system", "labels": labels,
                             "annotations": {"openclaw.dev/installation-checksum": digest},
                             "creationTimestamp": "2026-10-18T00:01:00Z",
                             "ownerReferences": [{"kind": "ReplicaSet", "controller": True,
                                                  "uid": "rs-" + component,
                                                  "name": "rs-" + component}]},
                "spec": copy.deepcopy(pod_spec),
                "status": {"phase": "Running", "conditions": [{"type": "Ready",
                                                                "status": "True"}],
                           "containerStatuses": [{"name": component, "ready": True,
                                                  "state": {"running": {"startedAt":
                                                      "2026-10-18T00:01:03Z"}}}]},
            }]
        return document, digest, image, {"secret": secret, "deployments": deployments,
                                         "replicaSets": replicasets, "pods": pods}

    def test_immutable_installation_snapshot_attests_both_loaded_drivers(self):
        document, digest, image, before = self._installation_snapshot()
        receipt = OCE.attest_stable_installation(document, digest, "ins_one", before,
                                                 copy.deepcopy(before), image)
        self.assertEqual(receipt["installationChecksum"], digest)
        self.assertEqual(receipt["podUids"], {"api": "pod-api", "worker": "pod-worker"})
        self.assertEqual(receipt["deploymentResourceVersions"],
                         {"api": "200", "worker": "200"})
        self.assertEqual(receipt["replicaSetResourceVersions"],
                         {"api": "300", "worker": "300"})
        self.assertEqual(receipt["podResourceVersions"],
                         {"api": "400", "worker": "400"})

    def test_historical_replicaset_does_not_block_current_pod_proof(self):
        document, digest, image, snapshot = self._installation_snapshot()
        old = copy.deepcopy(snapshot["replicaSets"]["api"][0])
        old["metadata"].update({"name": "rs-old", "uid": "rs-old", "resourceVersion": "299"})
        snapshot["replicaSets"]["api"].append(old)
        receipt = OCE.attest_stable_installation(document, digest, "ins_one", snapshot,
                                                 copy.deepcopy(snapshot), image)
        self.assertEqual(receipt["replicaSetUids"]["api"], "rs-api")
        old["metadata"]["ownerReferences"][0]["uid"] = "foreign-deployment"
        with self.assertRaisesRegex(OCE.Blocked, "ownership"):
            OCE.attest_stable_installation(document, digest, "ins_one", snapshot,
                                           copy.deepcopy(snapshot), image)

    def test_ready_controller_cannot_bypass_startup_file_with_changed_entrypoint(self):
        document, digest, image, baseline = self._installation_snapshot()
        for kind in ("deployments", "replicaSets", "pods"):
            for override in ({"args": ["apps/controller/src/other.mjs"]},
                             {"command": ["sh"], "args": ["apps/controller/src/server.mjs"]}):
                with self.subTest(kind=kind, override=override):
                    changed = copy.deepcopy(baseline)
                    workload = changed[kind]["api"]
                    if isinstance(workload, list):
                        workload = workload[0]
                    spec = workload["spec"]
                    if kind != "pods":
                        spec = spec["template"]["spec"]
                    spec["containers"][0].update(override)
                    with self.assertRaisesRegex(OCE.Blocked, "entrypoint changed"):
                        OCE.attest_stable_installation(document, digest, "ins_one", changed,
                                                       copy.deepcopy(changed), image)

    def test_attestation_rejects_mutable_stale_foreign_or_racing_inputs(self):
        document, digest, image, baseline = self._installation_snapshot()
        variants = []
        mutable = copy.deepcopy(baseline)
        mutable["secret"]["immutable"] = False
        variants.append(mutable)
        changed_data = copy.deepcopy(baseline)
        changed_data["secret"]["data"]["installation.yaml"] = base64.b64encode(
            b"different Installation").decode()
        variants.append(changed_data)
        stale = copy.deepcopy(baseline)
        stale["pods"]["worker"][0]["metadata"]["creationTimestamp"] = "2026-10-17T00:00:00Z"
        variants.append(stale)
        foreign = copy.deepcopy(baseline)
        foreign["deployments"]["api"]["spec"]["template"]["spec"]["volumes"][0]["secret"]["secretName"] = "other"
        variants.append(foreign)
        shadowed = copy.deepcopy(baseline)
        shadowed["pods"]["api"][0]["spec"]["containers"][0]["volumeMounts"].append({
            "name": "other", "mountPath": "/etc/openclaw"})
        variants.append(shadowed)
        for variant in variants:
            with self.assertRaises(OCE.Blocked):
                OCE.attest_stable_installation(document, digest, "ins_one", variant,
                                               copy.deepcopy(variant), image)
        raced = copy.deepcopy(baseline)
        raced["secret"]["metadata"]["resourceVersion"] = "101"
        with self.assertRaisesRegex(OCE.Blocked, "changed during proof"):
            OCE.attest_stable_installation(document, digest, "ins_one", baseline, raced, image)
        for kind in ("deployments", "replicaSets", "pods"):
            with self.subTest(kind=kind):
                raced = copy.deepcopy(baseline)
                workload = raced[kind]["worker"]
                if isinstance(workload, list):
                    workload = workload[0]
                workload["metadata"]["resourceVersion"] = "401"
                with self.assertRaisesRegex(OCE.Blocked, "changed during proof"):
                    OCE.attest_stable_installation(document, digest, "ins_one", baseline,
                                                   raced, image)
                del workload["metadata"]["resourceVersion"]
                with self.assertRaisesRegex(OCE.Blocked, "resource version"):
                    OCE.attest_stable_installation(document, digest, "ins_one", baseline,
                                                   raced, image)
        replaced_pod = copy.deepcopy(baseline)
        replaced_pod["pods"]["worker"][0]["metadata"]["uid"] = "replacement"
        with self.assertRaisesRegex(OCE.Blocked, "changed during proof"):
            OCE.attest_stable_installation(document, digest, "ins_one", baseline,
                                           replaced_pod, image)

    def test_kubernetes_snapshot_reads_only_fixed_cluster_and_objects(self):
        context = {"clusters": [{"cluster": {"server": OCE.KUBE_SERVER}}]}
        listing = {"items": []}
        objects = [context, {"kind": "Secret"}, {"kind": "Deployment"}, listing, listing,
                   {"kind": "Deployment"}, listing, listing]
        with patch.object(OCE.Kubernetes, "_json", side_effect=objects) as read:
            snapshot = OCE.Kubernetes().snapshot("a" * 64)
        self.assertEqual(snapshot["secret"], {"kind": "Secret"})
        self.assertEqual(read.call_count, 8)
        self.assertEqual(read.call_args_list[1].args,
                         ("-n", "openclaw-system", "get", "secret",
                          "occ-installation-startup-" + "a" * 32, "-o=json"))
        self.assertTrue(all(call.args[0] == "-n" for call in read.call_args_list[1:]))
        with patch.object(OCE.Kubernetes, "_json", return_value={"clusters": [{"cluster": {
                "server": "https://foreign.example"}}]}) as read:
            with self.assertRaisesRegex(OCE.Blocked, "context changed"):
                OCE.Kubernetes().snapshot("a" * 64)
            read.assert_called_once()

    def test_kubernetes_read_hides_error_and_secret_output(self):
        failed = subprocess.CompletedProcess(["kubectl"], 1, "private-body", "private-error")
        with patch.object(OCE.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(OCE.Blocked, "proof read failed") as raised:
                OCE.Kubernetes._json("get", "secret", "example")
        self.assertNotIn("private", str(raised.exception))
        with patch.object(OCE.subprocess, "run", return_value=subprocess.CompletedProcess(
                ["kubectl"], 0, "not-json", "")):
            with self.assertRaisesRegex(OCE.Blocked, "invalid JSON"):
                OCE.Kubernetes._json("get", "secret", "example")

    def test_check_proves_stable_current_pods_and_verify_remains_read_only(self):
        document, digest, image, snapshot = self._installation_snapshot()
        api = FakeAPI({"/installation": {"id": "ins_one", "name": "oce",
                                         "capabilities": {"openclaw": {"executionModes": ["embedded"]}}}})
        kube = FakeKubernetes([copy.deepcopy(snapshot) for _ in range(4)])
        with patch.object(OCE, "reviewed_installation", return_value=(document, digest, image)):
            self.assertEqual(OCE.check(self.config, api, kube)["installationId"], "ins_one")
            with self.assertRaisesRegex(OCE.Blocked, "journal is missing"):
                OCE.verify(self.config, api, kube)
        self.assertEqual(api.calls, [("GET", "/installation")])
        self.assertEqual(kube.calls, [digest] * 2)
        self.assertFalse((self.private / "journal.json").exists())

        unbound = copy.deepcopy(snapshot)
        del unbound["secret"]["metadata"]["annotations"]["openclaw.dev/installation-id"]
        kube = FakeKubernetes([unbound, copy.deepcopy(unbound)])
        with patch.object(OCE, "reviewed_installation", return_value=(document, digest, image)):
            with self.assertRaisesRegex(OCE.Blocked, "mutable or foreign"):
                OCE.check(self.config, api, kube)
        self.assertFalse((self.private / "journal.json").exists())

    def test_activation_requires_explicit_model_and_distinct_key_reference(self):
        active = copy.deepcopy(self.config)
        active["activationEnabled"] = True
        active["model"] = {}
        with self.assertRaisesRegex(OCE.Blocked, "explicit model"):
            OCE._validate_config(active)
        active["model"] = copy.deepcopy(self.config["model"])
        active["secrets"]["modelApiKey"] = "/homelab/litellm/openrouter-api-key"
        with self.assertRaisesRegex(OCE.Blocked, "dedicated model key"):
            OCE._validate_config(active)
        active["secrets"]["modelApiKey"] = "/homelab/openclaw-enterprise/model-api-key"
        OCE._validate_config(active)
        for field, value in (("provider", "attacker"), ("id", "anything"),
                             ("baseUrl", "https://unexpected.example"), ("api", "anthropic-messages")):
            changed = copy.deepcopy(active)
            changed["model"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(OCE.Blocked, "approved OpenRouter transport"):
                OCE._validate_config(changed)
        for field in ("provider", "id", "baseUrl", "api"):
            changed = copy.deepcopy(active)
            del changed["model"][field]
            with self.subTest(missing=field), self.assertRaisesRegex(OCE.Blocked, "approved OpenRouter transport"):
                OCE._validate_config(changed)
        active["model"]["alternateEndpoint"] = "https://unexpected.example"
        with self.assertRaisesRegex(OCE.Blocked, "approved OpenRouter transport"):
            OCE._validate_config(active)

    def test_legacy_retention_data_is_not_read_or_imported(self):
        class UnreadableLegacy(dict):
            def get(self, *_args):
                raise AssertionError("legacy data was read")

        config = {**self.config, "legacyRetention": UnreadableLegacy()}
        api = FakeAPI({"/installation": {"id": "ins_one"}})
        document, digest, image, snapshot = self._installation_snapshot()
        kube = FakeKubernetes([snapshot, copy.deepcopy(snapshot)])
        with patch.object(OCE, "reviewed_installation", return_value=(document, digest, image)):
            self.assertEqual(OCE.check(config, api, kube)["installationId"], "ins_one")
        self.assertEqual(api.calls, [("GET", "/installation")])

    def test_duplicate_or_unjournaled_logical_identity_is_foreign(self):
        owned = {"id": "ns_one", "name": "claw", "existingNamespace": "openclaw-agents"}
        with self.assertRaisesRegex(OCE.Blocked, "duplicate"):
            OCE.discover_exact([owned, {**owned, "id": "ns_two"}], "claw", "ns_one")
        with self.assertRaisesRegex(OCE.Blocked, "unjournaled"):
            OCE.discover_exact([owned], "claw", None)
        with self.assertRaisesRegex(OCE.Blocked, "changed identity"):
            OCE.discover_exact([{**owned, "existingNamespace": "other"}], "claw", "ns_one",
                               {"existingNamespace": "openclaw-agents"})
        self.assertEqual(OCE.discover_exact([owned], "claw", "ns_one",
                                            {"existingNamespace": "openclaw-agents"}), owned)

    def test_configuration_lost_response_requires_exact_owned_evidence_and_api_read(self):
        values = {"agents": {"defaults": {"model": "openrouter/free"}}}
        candidate = {
            "metadata": {"name": OCE.configuration_configmap_name("cfg_one"),
                         "namespace": "openclaw-agents",
                         "labels": {"app.kubernetes.io/managed-by": "openclaw-enterprise",
                                    "openclaw.dev/namespace": "ns_one",
                                    "openclaw.dev/configuration": "cfg_one"},
                         "annotations": {"openclaw.dev/namespace-id": "ns_one",
                                         "openclaw.dev/configuration-id": "cfg_one",
                                         "openclaw.dev/configuration-kind": "agent",
                                         "openclaw.dev/configuration-generation": "1",
                                         "openclaw.dev/configuration-created-at": "2026-10-18T00:00:00Z"}},
            "data": {"openclaw.json": json.dumps(values)},
        }
        exact = {"id": "cfg_one", "namespaceId": "ns_one", "kind": "agent",
                 "generation": 1, "values": values,
                 "createdAt": "2026-10-18T00:00:00Z"}
        with self.assertRaisesRegex(OCE.Blocked, "ambiguous"):
            OCE.recover_configuration([candidate, candidate], exact, "openclaw-agents")
        with self.assertRaisesRegex(OCE.Blocked, "foreign"):
            OCE.recover_configuration([{**candidate, "metadata": {
                **candidate["metadata"], "labels": {**candidate["metadata"]["labels"],
                                                  "openclaw.dev/namespace": "ns_other"}}}],
                exact, "openclaw-agents")
        self.assertEqual(OCE.recover_configuration([candidate], exact, "openclaw-agents"),
                         "cfg_one")

    def test_generation_conflict_is_not_silently_rebased(self):
        current = {"id": "cfg_one", "namespaceId": "ns_one", "generation": 3,
                   "values": {"agents": {"defaults": {"model": "old"}}}}
        with self.assertRaisesRegex(OCE.Blocked, "generation"):
            OCE.configuration_patch(current, {"agents": {"defaults": {"model": "new"}}}, 2)
        self.assertEqual(OCE.configuration_patch(current, {"agents": {"defaults": {
            "model": "new"}}}, 3)["expectedGeneration"], 3)

    def test_ambiguous_deploy_response_never_causes_second_deploy(self):
        baseline = {"rev_old"}
        matching = {"id": "rev_new", "agentId": "agt_one", "namespaceId": "ns_one",
                    "configurationId": "cfg_one", "configurationGeneration": 2}
        with self.assertRaisesRegex(OCE.Blocked, "unknown"):
            OCE.recover_revision([], baseline, "agt_one", "cfg_one", 2)
        with self.assertRaisesRegex(OCE.Blocked, "ambiguous"):
            OCE.recover_revision([matching, {**matching, "id": "rev_newer"}], baseline,
                                 "agt_one", "cfg_one", 2)
        self.assertEqual(OCE.recover_revision([matching], baseline, "agt_one", "cfg_one", 2),
                         "rev_new")

    def test_worker_restart_and_repeated_reconcile_do_not_redeploy(self):
        agent = {"id": "agt_one", "namespaceId": "ns_one", "status": "active",
                 "configurationId": "cfg_one", "desiredRuntimeState": "running",
                 "activeRevisionId": "rev_one"}
        revision = {"id": "rev_one", "agentId": "agt_one",
                    "configurationId": "cfg_one", "configurationGeneration": 2}
        status = {"deploymentId": "rev_one", "namespaceId": "ns_one",
                  "agentId": "agt_one", "status": "succeeded"}
        self.assertFalse(OCE.should_deploy(agent, revision, status, "cfg_one", 2))
        with self.assertRaisesRegex(OCE.Blocked, "in progress"):
            OCE.should_deploy(agent, revision, {**status, "status": "running"}, "cfg_one", 2)
        with self.assertRaisesRegex(OCE.Blocked, "failed"):
            OCE.should_deploy(agent, revision, {**status, "status": "failed"}, "cfg_one", 2)
        self.assertTrue(OCE.should_deploy(agent, revision, status, "cfg_one", 3))
        with self.assertRaisesRegex(OCE.Blocked, "evidence"):
            OCE.should_deploy(agent, revision, status, "cfg_one", True)
        with self.assertRaisesRegex(OCE.Blocked, "generation"):
            OCE.should_deploy(agent, {**revision, "configurationGeneration": True},
                              status, "cfg_one", 2)
        with self.assertRaisesRegex(OCE.Blocked, "identity"):
            OCE.should_deploy({**agent, "activeRevisionId": "rev_other"}, revision,
                              status, "cfg_one", 3)

    def test_revoked_or_partial_model_grant_blocks_deployment(self):
        role = {"id": "role_one", "namespaceId": "ns_one",
                "permissions": [{"action": "operate", "resourceKind": "secret"}]}
        binding = {"id": "binding_one", "namespaceId": "ns_one",
                   "subjectKind": "identity", "subjectId": "sp_one", "roleId": "role_one",
                   "resourceKind": "secret", "resourceId": "sec_one"}
        self.assertEqual(OCE.exact_model_grant([role], [binding], "ns_one", "sp_one", "sec_one"),
                         ("role_one", "binding_one"))
        with self.assertRaisesRegex(OCE.Blocked, "grant"):
            OCE.exact_model_grant([role], [], "ns_one", "sp_one", "sec_one")
        with self.assertRaisesRegex(OCE.Blocked, "grant"):
            OCE.exact_model_grant([role], [{**binding, "resourceId": "sec_other"}],
                                  "ns_one", "sp_one", "sec_one")

    def test_extra_agent_principal_grant_blocks_deployment(self):
        role = {"id": "role_one", "namespaceId": "ns_one",
                "permissions": [{"action": "operate", "resourceKind": "secret"}]}
        binding = {"id": "binding_one", "namespaceId": "ns_one",
                   "subjectKind": "identity", "subjectId": "sp_one", "roleId": "role_one",
                   "resourceKind": "secret", "resourceId": "sec_one"}
        broader_role = {"id": "role_admin", "namespaceId": "ns_one",
                        "permissions": [{"action": "administer", "resourceKind": "namespace"}]}
        for extra in ({**binding, "id": "binding_other", "resourceId": "sec_other"},
                      {**binding, "id": "binding_admin", "roleId": "role_admin",
                       "resourceKind": "namespace", "resourceId": "ns_one"}):
            with self.subTest(extra=extra["id"]), self.assertRaisesRegex(OCE.Blocked, "grant"):
                OCE.exact_model_grant([role, broader_role], [binding, extra],
                                      "ns_one", "sp_one", "sec_one")

    def test_protected_journal_rejects_permissions_symlinks_and_changed_source(self):
        path = self.private / "journal.json"
        with OCE.ProtectedJournal(path, "a" * 40, "b" * 64) as journal:
            with self.assertRaisesRegex(OCE.Blocked, "identity"):
                journal.save({"namespaceId": "sk-sensitive-value"})
            with self.assertRaisesRegex(OCE.Blocked, "desired hash"):
                journal.save({"desiredHash": {"apiKey": "do-not-store"}})
            journal.save({"namespaceId": "ns_one"})
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with self.assertRaisesRegex(OCE.Blocked, "source"):
            with OCE.ProtectedJournal(path, "c" * 40, "b" * 64):
                pass
        with self.assertRaisesRegex(OCE.Blocked, "source"):
            with OCE.ProtectedJournal(path, "a" * 40, "c" * 64):
                pass
        path.chmod(0o644)
        with self.assertRaisesRegex(OCE.Blocked, "mode"):
            with OCE.ProtectedJournal(path, "a" * 40, "b" * 64):
                pass
        path.unlink()
        path.symlink_to(self.private / "other")
        with self.assertRaisesRegex(OCE.Blocked, "symlink"):
            with OCE.ProtectedJournal(path, "a" * 40, "b" * 64):
                pass

    def test_namespace_reconcile_persists_exact_identity_without_recreating(self):
        api = NamespaceAPI()
        kube = FakeKubernetes([])
        with OCE.ProtectedJournal(self.private / "journal.json", self.config["source"]["revision"],
                                  OCE._identity_hash(self.config)) as journal:
            for _ in range(2):
                self.assertEqual(OCE.reconcile_namespace(self.config, api, journal, kube), "ns_one")
        self.assertEqual([call for call in api.calls if call[0] == "POST"],
                         [("POST", "/namespaces", {"name": "claw",
                                                  "existingNamespace": "openclaw-agents"})])
        state = json.loads((self.private / "journal.json").read_text())["state"]
        self.assertEqual(state, {"namespaceId": "ns_one"})
        self.assertEqual([call for call in kube.calls if isinstance(call, tuple)],
                         [("tenant-prepared", None, False),
                          ("tenant-prepared", "ns_one", False),
                          ("tenant-prepared", "ns_one", True),
                          ("tenant-prepared", "ns_one", False),
                          ("tenant-prepared", "ns_one", True)])
        changed_model = copy.deepcopy(self.config)
        changed_model["activationEnabled"] = True
        self.assertEqual(OCE._identity_hash(self.config), OCE._identity_hash(changed_model))

    def test_namespace_create_rechecks_unique_name_before_journaling(self):
        class CompetingNamespaceAPI(NamespaceAPI):
            def post(self, path, body):
                created = super().post(path, body)
                self.namespaces.append({**created, "id": "ns_other"})
                return created

        with OCE.ProtectedJournal(self.private / "journal.json", self.config["source"]["revision"],
                                  OCE._identity_hash(self.config)) as journal:
            with self.assertRaisesRegex(OCE.Blocked, "duplicate Enterprise logical identity"):
                OCE.reconcile_namespace(self.config, CompetingNamespaceAPI(), journal,
                                        FakeKubernetes([]))
            self.assertEqual(journal.state, {"pending": {"operation": "namespace-create"}})

    def test_lost_namespace_create_recovers_once_and_never_reposts(self):
        source = self.config["source"]["revision"]
        identity = OCE._identity_hash(self.config)
        path = self.private / "journal.json"
        api = NamespaceAPI(lost_response=True)
        with OCE.ProtectedJournal(path, source, identity) as journal:
            with self.assertRaisesRegex(OCE.Blocked, "request failed"):
                OCE.reconcile_namespace(self.config, api, journal, FakeKubernetes([]))
            self.assertEqual(journal.state["pending"], {"operation": "namespace-create"})
        with OCE.ProtectedJournal(path, source, identity) as journal:
            self.assertEqual(OCE.reconcile_namespace(self.config, api, journal,
                                                     FakeKubernetes([])), "ns_one")
            self.assertNotIn("pending", journal.state)
        self.assertEqual(sum(call[0] == "POST" for call in api.calls), 1)

    def test_namespace_preflight_blocks_first_post_and_pending_foreign_recovery(self):
        source = self.config["source"]["revision"]
        identity = OCE._identity_hash(self.config)
        path = self.private / "journal.json"
        api = NamespaceAPI()

        class RejectingKubernetes(FakeKubernetes):
            def tenant_prepared(self, namespace_id=None, require_claimed=False):
                super().tenant_prepared(namespace_id, require_claimed)
                raise OCE.Blocked("prepared tenant has a foreign NetworkPolicy")

        kube = RejectingKubernetes([])
        with OCE.ProtectedJournal(path, source, identity) as journal:
            with self.assertRaisesRegex(OCE.Blocked, "foreign NetworkPolicy"):
                OCE.reconcile_namespace(self.config, api, journal, kube)
            self.assertEqual(journal.state, {})
        self.assertEqual(kube.calls, [("tenant-prepared", None, False)])
        self.assertEqual(api.calls, [("GET", "/namespaces")])

        api = NamespaceAPI([{"id": "ns_one", "name": "claw",
                             "existingNamespace": "openclaw-agents", "status": "ready"}])
        kube = RejectingKubernetes([])
        with OCE.ProtectedJournal(path, source, identity) as journal:
            journal.save({"pending": {"operation": "namespace-create"}})
            with self.assertRaisesRegex(OCE.Blocked, "foreign NetworkPolicy"):
                OCE.reconcile_namespace(self.config, api, journal, kube)
            self.assertEqual(journal.state, {"pending": {"operation": "namespace-create"}})
        self.assertEqual(kube.calls, [("tenant-prepared", "ns_one", False)])
        self.assertEqual(api.calls, [("GET", "/namespaces")])

    def test_definitive_create_rejection_clears_pending_before_foreign_readback(self):
        source = self.config["source"]["revision"]
        identity = OCE._identity_hash(self.config)
        path = self.private / "journal.json"

        class RejectedNamespaceAPI(NamespaceAPI):
            def post(self, path, body):
                self.calls.append(("POST", path, copy.deepcopy(body)))
                raise OCE.DefinitiveRejection("Enterprise API returned HTTP 403")

        api = RejectedNamespaceAPI()
        with OCE.ProtectedJournal(path, source, identity) as journal:
            with self.assertRaisesRegex(OCE.DefinitiveRejection, "HTTP 403"):
                OCE.reconcile_namespace(self.config, api, journal, FakeKubernetes([]))
            self.assertEqual(journal.state, {})
            self.assertEqual(api.calls[0], ("GET", "/namespaces"))
            self.assertEqual(api.calls[-1], ("GET", "/namespaces"))
            self.assertEqual(sum(call[0] == "POST" for call in api.calls), 1)
            live_api = NamespaceAPI()
            self.assertEqual(OCE.reconcile_namespace(self.config, live_api, journal,
                                                     FakeKubernetes([])), "ns_one")
            self.assertEqual(sum(call[0] == "POST" for call in live_api.calls), 1)

        class AppearingNamespaceAPI(RejectedNamespaceAPI):
            def post(self, path, body):
                self.namespaces.append({"id": "ns_other", "name": "claw",
                                        "existingNamespace": "openclaw-agents", "status": "ready"})
                return super().post(path, body)

        other_path = self.private / "other-journal.json"
        with OCE.ProtectedJournal(other_path, source, identity) as journal:
            appearing_api = AppearingNamespaceAPI()
            with self.assertRaisesRegex(OCE.Blocked, "outcome changed"):
                OCE.reconcile_namespace(self.config, appearing_api, journal,
                                        FakeKubernetes([]))
            self.assertEqual(journal.state, {})
            with self.assertRaisesRegex(OCE.Blocked, "unjournaled Enterprise identity"):
                OCE.reconcile_namespace(self.config, appearing_api, journal,
                                        FakeKubernetes([]))

    def test_unknown_or_foreign_namespace_create_stays_pending(self):
        source = self.config["source"]["revision"]
        identity = OCE._identity_hash(self.config)
        path = self.private / "journal.json"
        foreign = {"id": "ns_foreign", "name": "claw",
                   "existingNamespace": "other", "status": "ready"}
        with OCE.ProtectedJournal(path, source, identity) as journal:
            with self.assertRaisesRegex(OCE.Blocked, "unjournaled"):
                OCE.reconcile_namespace(self.config, NamespaceAPI([foreign]), journal,
                                        FakeKubernetes([]))
            self.assertEqual(journal.state, {})
            journal.save({"pending": {"operation": "namespace-create"}})
        for existing, message in (([], "unknown"), ([foreign], "foreign"),
                                  ([foreign, foreign], "unknown")):
            api = NamespaceAPI(existing)
            with self.subTest(existing=existing), OCE.ProtectedJournal(path, source, identity) as journal:
                with self.assertRaisesRegex(OCE.Blocked, message):
                    OCE.reconcile_namespace(self.config, api, journal, FakeKubernetes([]))
                self.assertEqual(sum(call[0] == "POST" for call in api.calls), 0)
        malformed = NamespaceAPI([{"id": "ns_one/installation", "name": "claw",
                                   "existingNamespace": "openclaw-agents", "status": "ready"}])
        with OCE.ProtectedJournal(path, source, identity) as journal:
            with self.assertRaisesRegex(OCE.Blocked, "Namespace ID is invalid"):
                OCE.reconcile_namespace(self.config, malformed, journal, FakeKubernetes([]))
        self.assertEqual(malformed.calls, [("GET", "/namespaces")])

    def test_namespace_exact_readback_and_journal_source_are_required(self):
        source = self.config["source"]["revision"]
        identity = OCE._identity_hash(self.config)
        path = self.private / "journal.json"
        api = NamespaceAPI([{"id": "ns_one", "name": "claw",
                             "existingNamespace": "openclaw-agents", "status": "provisioning"}])
        with OCE.ProtectedJournal(path, source, identity) as journal:
            journal.save({"namespaceId": "ns_one"})
            with self.assertRaisesRegex(OCE.Blocked, "readback"):
                OCE.reconcile_namespace(self.config, api, journal, FakeKubernetes([]))
        changed = copy.deepcopy(self.config)
        changed["namespace"]["existingNamespace"] = "foreign"
        with self.assertRaisesRegex(OCE.Blocked, "source"):
            with OCE.ProtectedJournal(path, source, OCE._identity_hash(changed)):
                pass

    def test_prepared_namespace_and_rbac_are_exact(self):
        context = {"clusters": [{"cluster": {"server": OCE.KUBE_SERVER}}]}
        namespace = {"metadata": {"name": "openclaw-agents", "resourceVersion": "17",
                                  "annotations": {"openclaw.dev/namespace-lifecycle": "external"},
                                  "labels": {"pod-security.kubernetes.io/enforce": "restricted",
                                             "pod-security.kubernetes.io/audit": "restricted",
                                             "pod-security.kubernetes.io/warn": "restricted"}},
                     "status": {"phase": "Active"}}
        policies = {"items": []}
        roles = (("openclaw-enterprise-worker", "oce-openclaw-tenant-worker", "openclaw-enterprise-worker"),
                 ("openclaw-enterprise-api-secrets", "oce-openclaw-tenant-api", "openclaw-enterprise-api"),
                 ("openclaw-enterprise-api-configuration", "oce-openclaw-tenant-configuration", "openclaw-enterprise-api"))
        bindings = [{"metadata": {"name": name, "namespace": "openclaw-agents"},
                     "roleRef": {"apiGroup": "rbac.authorization.k8s.io",
                                 "kind": "ClusterRole", "name": role},
                     "subjects": [{"kind": "ServiceAccount", "name": subject,
                                   "namespace": "openclaw-system"}]}
                    for name, role, subject in roles]
        cluster_roles = [
            {"metadata": {"name": role},
             "rules": [{"apiGroups": [group], "resources": list(resources),
                        "verbs": list(verbs)}
                       for group, resources, verbs in OCE.TENANT_ROLE_RULES[role]]}
            for _, role, _ in roles]
        prepared = [context, namespace, policies]
        for cluster_role, binding in zip(cluster_roles, bindings):
            prepared.extend((cluster_role, binding))
        with patch.object(OCE.Kubernetes, "_json", side_effect=prepared):
            OCE.Kubernetes().tenant_prepared()
        terminating = copy.deepcopy(namespace)
        terminating["metadata"]["deletionTimestamp"] = "2026-10-19T00:00:00Z"
        with patch.object(OCE.Kubernetes, "_json", side_effect=[context, terminating]):
            with self.assertRaisesRegex(OCE.Blocked, "Namespace is absent or changed"):
                OCE.Kubernetes().tenant_prepared()
        for mode in ("enforce", "audit", "warn"):
            wrong_namespace = copy.deepcopy(namespace)
            wrong_namespace["metadata"]["labels"].pop("pod-security.kubernetes.io/" + mode)
            with self.subTest(mode=mode), patch.object(
                    OCE.Kubernetes, "_json", side_effect=[context, wrong_namespace]):
                with self.assertRaisesRegex(OCE.Blocked, "Namespace is absent or changed"):
                    OCE.Kubernetes().tenant_prepared()
        foreign_namespace = copy.deepcopy(namespace)
        foreign_namespace["metadata"]["labels"]["openclaw.dev/namespace"] = "ns_other"
        with patch.object(OCE.Kubernetes, "_json", side_effect=[context, foreign_namespace]):
            with self.assertRaisesRegex(OCE.Blocked, "foreign ownership"):
                OCE.Kubernetes().tenant_prepared()
        claimed = copy.deepcopy(namespace)
        claimed["metadata"]["labels"].update({"openclaw.dev/namespace": "ns_one",
                                                 "openclaw.dev/gateway-namespace": "ns_one"})
        claimed["metadata"]["annotations"]["openclaw.dev/namespace-id"] = "ns_one"
        owned_policies = [
            {"kind": "NetworkPolicy", "metadata": {
                "name": name, "namespace": "openclaw-agents",
                "labels": {"app.kubernetes.io/managed-by": "openclaw-enterprise",
                           "openclaw.dev/namespace": "ns_one"},
                "annotations": {"openclaw.dev/namespace-id": "ns_one"}},
             "spec": copy.deepcopy(spec)}
            for name, spec in OCE.REQUIRED_TENANT_POLICY_SPECS.items()]
        replay = [context, claimed, {"items": owned_policies}] + prepared[3:]
        with patch.object(OCE.Kubernetes, "_json", side_effect=replay):
            OCE.Kubernetes().tenant_prepared("ns_one", require_claimed=True)
        extra_policy = copy.deepcopy(owned_policies[0])
        extra_policy["metadata"]["name"] = "allow-all"
        extra_policy["spec"] = {"podSelector": {}, "policyTypes": ["Ingress"],
                                "ingress": [{}]}
        for changed_policies in ([], owned_policies[1:],
                                 [*owned_policies, extra_policy],
                                 [{**owned_policies[0], "spec": {"podSelector": {},
                                   "policyTypes": ["Ingress"]}}, *owned_policies[1:]]):
            with self.subTest(count=len(changed_policies)), patch.object(
                    OCE.Kubernetes, "_json",
                    side_effect=[context, claimed, {"items": changed_policies}] + prepared[3:]):
                with self.assertRaisesRegex(OCE.Blocked, "NetworkPolicy (set )?is absent or changed"):
                    OCE.Kubernetes().tenant_prepared("ns_one", require_claimed=True)
        with patch.object(OCE.Kubernetes, "_json", side_effect=[context, namespace,
                                                                 {"items": [owned_policies[0]]}]):
            with self.assertRaisesRegex(OCE.Blocked, "foreign NetworkPolicy"):
                OCE.Kubernetes().tenant_prepared()
        foreign_policy = copy.deepcopy(owned_policies[0])
        foreign_policy["metadata"]["annotations"]["openclaw.dev/namespace-id"] = "ns_other"
        with patch.object(OCE.Kubernetes, "_json", side_effect=[context, claimed,
                                                                 {"items": [foreign_policy]}]):
            with self.assertRaisesRegex(OCE.Blocked, "foreign NetworkPolicy"):
                OCE.Kubernetes().tenant_prepared("ns_one")
        unclaimed = [context, namespace, policies] + prepared[3:]
        with patch.object(OCE.Kubernetes, "_json", side_effect=unclaimed):
            with self.assertRaisesRegex(OCE.Blocked, "has not been claimed"):
                OCE.Kubernetes().tenant_prepared("ns_one", require_claimed=True)
        wrong = copy.deepcopy(bindings)
        wrong[1]["roleRef"]["name"] = "cluster-admin"
        malformed = [context, namespace, policies]
        for cluster_role, binding in zip(cluster_roles, wrong):
            malformed.extend((cluster_role, binding))
        with patch.object(OCE.Kubernetes, "_json", side_effect=malformed):
            with self.assertRaisesRegex(OCE.Blocked, "RBAC"):
                OCE.Kubernetes().tenant_prepared()
        broad_roles = copy.deepcopy(cluster_roles)
        broad_roles[0]["rules"][0]["verbs"].append("*")
        broad = [context, namespace, policies]
        for cluster_role, binding in zip(broad_roles, bindings):
            broad.extend((cluster_role, binding))
        with patch.object(OCE.Kubernetes, "_json", side_effect=broad):
            with self.assertRaisesRegex(OCE.Blocked, "ClusterRole"):
                OCE.Kubernetes().tenant_prepared()


class InactiveAgentReconciliation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oce-agent-")
        self.addCleanup(self.temp.cleanup)
        private = Path(self.temp.name).resolve() / "private"
        private.mkdir(mode=0o700)
        self.config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        self.config["privateJournal"]["mountPath"] = str(private / "journal.json")
        self.api = TenantAPI()
        self.kube = TenantKubernetes(self.api)
        with OCE.ProtectedJournal(private / "journal.json", self.config["source"]["revision"],
                                  OCE._identity_hash(self.config)) as journal:
            journal.save({"installationId": "ins_one", "namespaceId": "ns_one"})

    def _reconcile(self):
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}):
            return OCE.reconcile(self.config, self.api, self.kube, "a" * 40)

    def test_openrouter_wire_id_has_supported_native_provider(self):
        values = OCE.desired_configuration(self.config)
        self.assertEqual(values["agents"]["defaults"]["model"], "openai/openrouter/free")
        self.assertEqual(values["agents"]["defaults"]["models"], {
            "openai/openrouter/free": {"agentRuntime": {"id": "openclaw"}}})
        self.assertEqual(values["models"]["providers"], {"openai": {
            "baseUrl": "https://openrouter.ai/api/v1", "api": "openai-completions",
            "apiKey": {"source": "env", "provider": "model", "id": "OPENAI_API_KEY"},
            "models": [{"id": "openrouter/free", "name": "openrouter/free"}]}})
        self.assertEqual(values["gateway"]["controlUi"], {"enabled": False})
        self.assertEqual(values["secrets"], {"providers": {
            "model": {"source": "env", "allowlist": ["OPENAI_API_KEY"]}}})
        self.assertEqual(values["tools"], {"deny": ["*"]})
        bad = copy.deepcopy(self.config)
        bad["model"]["provider"] = "openrouter"
        with self.assertRaisesRegex(OCE.Blocked, "approved OpenRouter transport"):
            OCE.desired_configuration(bad)

    def test_inactive_first_reconcile_is_idempotent_and_verify_has_no_mutation(self):
        self.assertEqual(self._reconcile()["desiredRuntimeState"], "stopped")
        self.assertEqual(self._reconcile()["agentId"], "agt_one")
        writes = [call for call in self.api.calls if call[0] == "POST"]
        self.assertEqual([call[1] for call in writes], [
            "/namespaces/ns_one/configurations", "/namespaces/ns_one/agents"])
        with patch.object(OCE, "check", return_value={"installationId": "ins_one"}):
            self.assertEqual(OCE.verify(self.config, self.api, self.kube)["agentId"], "agt_one")
        self.assertEqual([call for call in self.api.calls if call[0] == "POST"], writes)
        state, _ = OCE.read_journal(self.config["privateJournal"]["mountPath"],
                                    self.config["source"]["revision"],
                                    OCE._identity_hash(self.config))
        self.assertEqual(state["configurationGeneration"], 1)
        self.assertEqual(state["servicePrincipalId"], "sp_one")
        self.assertNotIn("pending", state)

    def test_lost_configuration_response_adopts_owned_configmap_without_repost(self):
        self.api.lose = "configuration"
        with self.assertRaisesRegex(OCE.Blocked, "request failed"):
            self._reconcile()
        state, _ = OCE.read_journal(self.config["privateJournal"]["mountPath"],
                                    self.config["source"]["revision"],
                                    OCE._identity_hash(self.config))
        self.assertEqual(state["pending"]["operation"], "configuration-create")
        self.assertEqual(self._reconcile()["agentId"], "agt_one")
        posts = [call for call in self.api.calls if call[0] == "POST"]
        self.assertEqual([call[1] for call in posts], [
            "/namespaces/ns_one/configurations", "/namespaces/ns_one/agents"])

    def test_lost_agent_response_adopts_exact_stopped_agent_without_repost(self):
        self.api.lose = "agent"
        with self.assertRaisesRegex(OCE.Blocked, "request failed"):
            self._reconcile()
        state, _ = OCE.read_journal(self.config["privateJournal"]["mountPath"],
                                    self.config["source"]["revision"],
                                    OCE._identity_hash(self.config))
        self.assertEqual(state["pending"]["operation"], "agent-create")
        self.api.agents["agt_unrelated"] = {**self.api.agents["agt_one"],
                                            "id": "agt_unrelated", "name": "other"}
        self.assertEqual(self._reconcile()["agentId"], "agt_one")
        self.assertEqual(len([call for call in self.api.calls if call[0] == "POST" and
                              call[1] == "/namespaces/ns_one/agents"]), 1)

    def test_agent_create_rechecks_unique_name_before_journaling(self):
        original_post = self.api.post

        def create_with_competing_agent(path, body):
            created = original_post(path, body)
            if path.endswith("/agents"):
                self.api.agents["agt_other"] = {**created, "id": "agt_other"}
            return created

        with patch.object(self.api, "post", side_effect=create_with_competing_agent):
            with self.assertRaisesRegex(OCE.Blocked, "duplicate Enterprise logical identity"):
                self._reconcile()
        state, _ = OCE.read_journal(self.config["privateJournal"]["mountPath"],
                                    self.config["source"]["revision"],
                                    OCE._identity_hash(self.config))
        self.assertEqual(state["pending"]["operation"], "agent-create")
        self.assertNotIn("agentId", state)

    def test_definitively_rejected_configuration_clears_intent_only_after_absence(self):
        with patch.object(self.api, "post", side_effect=OCE.DefinitiveRejection("HTTP 403")):
            with self.assertRaisesRegex(OCE.DefinitiveRejection, "HTTP 403"):
                self._reconcile()
        state, _ = OCE.read_journal(self.config["privateJournal"]["mountPath"],
                                    self.config["source"]["revision"],
                                    OCE._identity_hash(self.config))
        self.assertNotIn("pending", state)
        self.assertEqual(self._reconcile()["agentId"], "agt_one")

    def test_definitively_rejected_agent_clears_intent_only_after_absence(self):
        original_post = self.api.post

        def reject_agent(path, body):
            if path.endswith("/agents"):
                self.api.agents["agt_unrelated"] = {"id": "agt_unrelated", "name": "other"}
                raise OCE.DefinitiveRejection("HTTP 403")
            return original_post(path, body)

        with patch.object(self.api, "post", side_effect=reject_agent):
            with self.assertRaisesRegex(OCE.DefinitiveRejection, "HTTP 403"):
                self._reconcile()
        state, _ = OCE.read_journal(self.config["privateJournal"]["mountPath"],
                                    self.config["source"]["revision"],
                                    OCE._identity_hash(self.config))
        self.assertEqual(state["configurationId"], "cfg_one")
        self.assertNotIn("pending", state)
        self.assertEqual(self._reconcile()["agentId"], "agt_one")

    def test_rejected_creates_never_adopt_competing_objects(self):
        def competing_configuration(path, body):
            self.api.configurations["cfg_foreign"] = {
                "id": "cfg_foreign", "namespaceId": "ns_one", "kind": "agent",
                "createdAt": "2026-10-19T00:00:00.000Z", "generation": 1,
                "values": copy.deepcopy(body["values"])}
            raise OCE.DefinitiveRejection("HTTP 403")

        with patch.object(self.api, "post", side_effect=competing_configuration):
            with self.assertRaisesRegex(OCE.Blocked, "Configuration create outcome changed"):
                self._reconcile()
        state, _ = OCE.read_journal(self.config["privateJournal"]["mountPath"],
                                    self.config["source"]["revision"],
                                    OCE._identity_hash(self.config))
        self.assertNotIn("pending", state)
        with self.assertRaisesRegex(OCE.Blocked, "unjournaled Enterprise Configuration"):
            self._reconcile()

        self.api.configurations.clear()
        self.assertEqual(self._reconcile()["agentId"], "agt_one")
        self.api.agents.pop("agt_one")
        with OCE.ProtectedJournal(self.config["privateJournal"]["mountPath"],
                                  self.config["source"]["revision"],
                                  OCE._identity_hash(self.config)) as journal:
            state = dict(journal.state)
            state.pop("agentId")
            state.pop("servicePrincipalId")
            journal.save(state)

        def competing_agent(path, body):
            self.api.agents["agt_foreign"] = {"id": "agt_foreign", "name": body["name"]}
            raise OCE.DefinitiveRejection("HTTP 403")

        with patch.object(self.api, "post", side_effect=competing_agent):
            with self.assertRaisesRegex(OCE.Blocked, "Agent create outcome changed"):
                self._reconcile()
        state, _ = OCE.read_journal(self.config["privateJournal"]["mountPath"],
                                    self.config["source"]["revision"],
                                    OCE._identity_hash(self.config))
        self.assertNotIn("pending", state)
        with self.assertRaisesRegex(OCE.Blocked, "unjournaled Enterprise Agent"):
            self._reconcile()

    def test_foreign_configuration_and_changed_generation_block(self):
        self.api.configurations["cfg_foreign"] = {
            "id": "cfg_foreign", "namespaceId": "ns_one", "kind": "agent",
            "createdAt": "2026-10-19T00:00:00.000Z", "generation": 1, "values": {}}
        with self.assertRaisesRegex(OCE.Blocked, "unjournaled Enterprise Configuration"):
            self._reconcile()
        self.api.configurations.clear()
        self._reconcile()
        self.api.configurations["cfg_one"]["generation"] = 2
        with self.assertRaisesRegex(OCE.Blocked, "Configuration readback changed"):
            self._reconcile()

    def test_unknown_configuration_create_does_not_repost(self):
        with patch.object(self.api, "post", side_effect=OCE.Blocked("lost response")) as post:
            with self.assertRaisesRegex(OCE.Blocked, "lost response"):
                self._reconcile()
            with self.assertRaisesRegex(OCE.Blocked, "unknown Configuration create outcome"):
                self._reconcile()
        post.assert_called_once()

    def test_configuration_candidate_lookup_is_scoped(self):
        drifted = {"metadata": {"name": OCE.configuration_configmap_name("cfg_one"),
                                "labels": {"app.kubernetes.io/managed-by": "foreign"}}}
        annotated = {"metadata": {"name": "renamed", "annotations": {
            "openclaw.dev/configuration-id": "cfg_other"}}}
        unrelated = {"metadata": {"name": "kube-root-ca.crt"}}
        with patch.object(OCE.Kubernetes, "_json", return_value={
                "items": [drifted, annotated, unrelated]}) as read:
            self.assertEqual(OCE.Kubernetes().configuration_candidates("ns_one"),
                             [drifted, annotated])
        read.assert_called_once_with(
            "-n", "openclaw-agents", "get", "configmaps", "-o=json")

    def test_partially_labeled_configuration_blocks_create(self):
        drifted = {"metadata": {"name": OCE.configuration_configmap_name("cfg_one"),
                                "labels": {"app.kubernetes.io/managed-by": "foreign"}}}
        with patch.object(self.kube, "configuration_candidates", return_value=[drifted]):
            with self.assertRaisesRegex(OCE.Blocked, "unjournaled Enterprise Configuration"):
                self._reconcile()
        self.assertFalse(any(call[0] == "POST" for call in self.api.calls))

    def test_verify_blocks_duplicate_name_or_changed_principal(self):
        self._reconcile()
        with patch.object(OCE, "check", return_value={"installationId": "ins_one"}):
            self.api.agents["agt_second"] = {**self.api.agents["agt_one"], "id": "agt_second"}
            with self.assertRaisesRegex(OCE.Blocked, "duplicate Enterprise logical identity"):
                OCE.verify(self.config, self.api, self.kube)
            self.api.agents.pop("agt_second")
            self.api.agents["agt_one"]["servicePrincipalId"] = "sp_foreign"
            with self.assertRaisesRegex(OCE.Blocked, "inactive Enterprise Agent changed"):
                OCE.verify(self.config, self.api, self.kube)

    def test_verify_rejects_duplicate_logical_namespace(self):
        self._reconcile()
        original_get = self.api.get

        def competing_namespace(path):
            result = original_get(path)
            if path == "/namespaces":
                result.append({**self.api.namespace, "id": "ns_other"})
            return result

        with patch.object(self.api, "get", side_effect=competing_namespace):
            with patch.object(OCE, "check", return_value={"installationId": "ins_one"}):
                with self.assertRaisesRegex(OCE.Blocked, "duplicate Enterprise logical identity"):
                    OCE.verify(self.config, self.api, self.kube)

    def test_verify_rejects_configuration_ownership_drift(self):
        self._reconcile()
        candidates = self.kube.configuration_candidates("ns_one")
        with patch.object(OCE, "check", return_value={"installationId": "ins_one"}):
            with patch.object(self.kube, "configuration_candidates", return_value=candidates * 2):
                with self.assertRaisesRegex(OCE.Blocked, "Configuration ConfigMap set is ambiguous"):
                    OCE.verify(self.config, self.api, self.kube)
            drifted = copy.deepcopy(candidates[0])
            drifted["metadata"]["labels"]["openclaw.dev/configuration"] = "cfg_foreign"
            with patch.object(self.kube, "configuration_candidates", return_value=[drifted]):
                with self.assertRaisesRegex(OCE.Blocked, "foreign Configuration recovery candidate"):
                    OCE.verify(self.config, self.api, self.kube)

    def test_reconcile_rejects_auth_bound_to_journaled_stopped_agent(self):
        self._reconcile()
        self.api.agents["agt_one"]["harnessAuth"] = {"method": "api_key"}
        with self.assertRaisesRegex(OCE.Blocked, "journaled Agent is not inactive"):
            self._reconcile()


if __name__ == "__main__":
    unittest.main()
