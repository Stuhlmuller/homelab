#!/usr/bin/env python3
"""Fail-closed fixtures for read-only canary traffic probes."""

import importlib.util
import json
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/network-policy-qualification.py"


def load_module():
    spec = importlib.util.spec_from_file_location("network_policy_qualification", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CanaryQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_reviewed_fixture_commands_match_manifest(self):
        if not shutil.which("yq"):
            self.skipTest("yq is provided by the Nix validation shell")
        output = subprocess.run(
            ["yq", "ea", "-o=json", '[select(.kind == "Pod")]',
             str(ROOT / "clusters/homelab/platform/network-policy/canary/fixtures.yaml")],
            check=True, capture_output=True, text=True, timeout=10,
        )
        pods = json.loads(output.stdout)
        self.assertEqual({pod["metadata"]["name"] for pod in pods},
                         {"npq-client", "npq-allowed", "npq-denied"})
        for pod in pods:
            role = pod["metadata"]["labels"]["role"]
            container, = pod["spec"]["containers"]
            with self.subTest(role=role):
                self.assertEqual(container["command"], self.module.FIXTURE_COMMANDS[role])
                self.assertNotIn("args", container)
                self.assertEqual(container["securityContext"], self.module.FIXTURE_SECURITY)

    def test_remote_probe_emits_outcome_marker(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            def serve():
                connection, _ = listener.accept()
                with connection:
                    connection.sendall(b"npq-ok")
            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            allowed = subprocess.run([sys.executable, "-c", self.module.PROBE,
                                      "127.0.0.1", str(port), "TCP"],
                                     capture_output=True, text=True, timeout=5)
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        denied = subprocess.run([sys.executable, "-c", self.module.PROBE,
                                 "127.0.0.1", str(port), "TCP"],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual((allowed.returncode, allowed.stdout.strip()), (0, "NPQ_ALLOWED"))
        self.assertEqual((denied.returncode, denied.stdout.strip()), (7, "NPQ_DENIED"))

    def test_traffic_requires_baseline_and_all_denials(self):
        pods = {name: {"status": {"podIP": f"10.42.0.{index}"}}
                for index, name in enumerate(("npq-client", "npq-allowed", "npq-denied"), 1)}
        def response(permitted, marker=None):
            return subprocess.CompletedProcess([], 0 if permitted else 7,
                                               (marker or ("NPQ_ALLOWED" if permitted else "NPQ_DENIED")) + "\n", "")
        expected = [response(case[-1]) for case in self.module.CASES]
        dns = [{"source": "npq-client", "target": "kube-dns", "port": 53,
                "protocol": protocol, "permitted": True} for protocol in ("TCP", "UDP")]
        with (patch.object(self.module, "probe", side_effect=expected) as probe,
              patch.object(self.module, "dns_matrix", return_value=dns) as dns_probe):
            result = self.module.traffic_matrix(pods)
            self.assertEqual(len(result), len(expected) + 2)
            self.assertEqual(result[-2:], dns)
            self.assertEqual(probe.call_count, len(expected))
            dns_probe.assert_called_once_with()
        for index in (0, 5, 7):
            wrong = list(expected)
            wrong[index] = response(not self.module.CASES[index][-1])
            with (self.subTest(index=index),
                  patch.object(self.module, "probe", side_effect=wrong),
                  patch.object(self.module, "dns_matrix", return_value=dns)):
                with self.assertRaisesRegex(ValueError, "traffic mismatch"):
                    self.module.traffic_matrix(pods)
        with (patch.object(self.module, "probe", side_effect=[
                subprocess.CompletedProcess([], 1, "", "kubectl failed"), *expected[1:]]),
              patch.object(self.module, "dns_matrix", return_value=dns)):
            with self.assertRaisesRegex(ValueError, "traffic mismatch"):
                self.module.traffic_matrix(pods)
        wrong = list(expected)
        wrong[5] = response(False, "kubectl failed")
        with (patch.object(self.module, "probe", side_effect=wrong),
              patch.object(self.module, "dns_matrix", return_value=dns)):
            with self.assertRaisesRegex(ValueError, "traffic mismatch"):
                self.module.traffic_matrix(pods)

    def test_dns_requires_remote_success_marker(self):
        service = {"metadata": {"name": "kube-dns", "namespace": "kube-system"},
                   "spec": {"clusterIP": "10.96.0.10", "ipFamilies": ["IPv4"],
                            "selector": {"k8s-app": "kube-dns"},
                            "ports": [{"protocol": protocol, "port": 53, "targetPort": 53}
                                      for protocol in ("TCP", "UDP")]}}
        kubernetes = {"metadata": {"name": "kubernetes", "namespace": "default"},
                      "spec": {"clusterIP": "10.96.0.1", "ipFamilies": ["IPv4"]}}
        objects = {("-n", "kube-system", "get", "service", "kube-dns"): service,
                   ("-n", "default", "get", "service", "kubernetes"): kubernetes}
        success = subprocess.CompletedProcess([], 0, "NPQ_DNS_ALLOWED\n", "")
        with (patch.object(self.module, "kubernetes_json", side_effect=lambda *args: objects[args]),
              patch.object(self.module, "probe_dns", side_effect=[success, success]) as probe):
            results = self.module.dns_matrix()
            self.assertEqual([item["observed"] for item in results],
                             ["NPQ_DNS_ALLOWED", "NPQ_DNS_ALLOWED"])
            probe.assert_has_calls([call("npq-client", "10.96.0.10", protocol, "10.96.0.1")
                                    for protocol in ("TCP", "UDP")])
        with (patch.object(self.module, "kubernetes_json", side_effect=lambda *args: objects[args]),
              patch.object(self.module, "probe_dns", return_value=
                           subprocess.CompletedProcess([], 0, "", ""))):
            with self.assertRaisesRegex(ValueError, "DNS TCP probe failed"):
                self.module.dns_matrix()

    def test_dns_probe_requires_complete_expected_a_record(self):
        def run_probe(protocol, answer, spoof=False):
            kind = socket.SOCK_STREAM if protocol == "TCP" else socket.SOCK_DGRAM
            with socket.socket(socket.AF_INET, kind) as listener:
                listener.bind(("127.0.0.1", 0))
                listener.settimeout(5)
                if protocol == "TCP":
                    listener.listen()
                port = listener.getsockname()[1]
                def serve():
                    if protocol == "TCP":
                        connection, _ = listener.accept()
                        with connection:
                            stream = connection.makefile("rb")
                            length = struct.unpack("!H", stream.read(2))[0]
                            query = stream.read(length)
                            response = answer(query)
                            connection.sendall(struct.pack("!H", len(response)) + response)
                    else:
                        query, address = listener.recvfrom(4096)
                        if spoof:
                            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:
                                other.bind(("127.0.0.1", 0))
                                other.sendto(answer(query), address)
                        else:
                            listener.sendto(answer(query), address)
                thread = threading.Thread(target=serve, daemon=True)
                thread.start()
                result = subprocess.run(
                    [sys.executable, "-c", self.module.DNS_PROBE,
                     "127.0.0.1", protocol, "10.96.0.1", str(port)],
                    capture_output=True, text=True, timeout=5,
                )
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
                return result

        def response(query, address=None, truncated=False):
            flags = b"\x83\x80" if truncated else b"\x81\x80"
            header = query[:2] + flags + query[4:6] + b"\x00\x01\x00\x00\x00\x00"
            question = query[12:]
            if address is None:
                return header + question
            record = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4)
            return header + question + record + socket.inet_aton(address)

        for protocol in ("TCP", "UDP"):
            for address, truncated, expected_code in (("10.96.0.1", False, 0),
                                                      (None, False, 8),
                                                      ("10.96.0.2", False, 8),
                                                      ("10.96.0.1", True, 8)):
                with self.subTest(protocol=protocol, address=address, truncated=truncated):
                    result = run_probe(protocol,
                                       lambda query: response(query, address, truncated))
                    self.assertEqual(result.returncode, expected_code, result.stderr)
                    self.assertEqual(result.stdout.strip(),
                                     "NPQ_DNS_ALLOWED" if expected_code == 0 else "")
        result = run_probe("UDP", lambda query: response(query, "10.96.0.1"), spoof=True)
        self.assertEqual(result.returncode, 8, result.stderr)

    def test_inspection_refuses_foreign_policy_or_untainted_node(self):
        node = {"metadata": {"name": "zimaboard-0", "uid": "node-uid",
                             "labels": {self.module.CANARY_KEY: "true"}},
                "spec": {"taints": [{"key": self.module.CANARY_KEY,
                                     "value": "true", "effect": "NoSchedule",
                                     "timeAdded": "2026-10-18T00:00:00Z"}]},
                "status": {"conditions": [{"type": "Ready", "status": "True"}],
                           "nodeInfo": {"bootID": "boot-id"}}}
        server_node = {"metadata": {"name": self.module.FIXTURE_NODE,
                                    "uid": "server-node-uid",
                                    "labels": {self.module.HOSTNAME_LABEL: self.module.FIXTURE_NODE}},
                       "spec": {"taints": []},
                       "status": {"conditions": [{"type": "Ready", "status": "True"}],
                                  "nodeInfo": {"bootID": "server-boot-id"}}}
        namespace = {"metadata": {"labels": {
            "pod-security.kubernetes.io/enforce": "restricted"}}}
        pods = {}
        for name, role in (("npq-client", "client"), ("npq-allowed", "allowed"),
                           ("npq-denied", "denied")):
            pods[name] = {"metadata": {"name": name, "uid": f"{name}-uid",
                                      "labels": {"role": role}},
                          "spec": {"nodeName": ("zimaboard-0" if role == "client" else
                                                self.module.FIXTURE_NODE),
                                   "nodeSelector": ({self.module.CANARY_KEY: "true"}
                                                    if role == "client" else
                                                    {self.module.HOSTNAME_LABEL:
                                                     self.module.FIXTURE_NODE}),
                                   "tolerations": ([{"key": self.module.CANARY_KEY,
                                                     "operator": "Equal", "value": "true",
                                                     "effect": "NoSchedule"}]
                                                    if role == "client" else []),
                                   "automountServiceAccountToken": False,
                                   "securityContext": {"runAsUser": 65532,
                                                       "runAsNonRoot": True,
                                                       "seccompProfile": {"type": "RuntimeDefault"}},
                                   "containers": [{"name": "probe" if role == "client" else "server",
                                                   "image": self.module.IMAGE,
                                                   "command": self.module.FIXTURE_COMMANDS[role],
                                                   "securityContext": {
                                                       "allowPrivilegeEscalation": False,
                                                       "readOnlyRootFilesystem": True,
                                                       "capabilities": {"drop": ["ALL"]}}}]},
                          "status": {"phase": "Running", "podIP": "10.42.0.2",
                                     "conditions": [{"type": "Ready", "status": "True"}]}}
            container = pods[name]["spec"]["containers"][0]
            container["resources"] = json.loads(json.dumps(self.module.FIXTURE_RESOURCES))
            container["imagePullPolicy"] = "Always"
            if role != "client":
                container["ports"] = self.module.SERVER_PORTS
                defaulted_probe = {**self.module.SERVER_PROBE,
                                   "periodSeconds": 10, "timeoutSeconds": 1,
                                   "failureThreshold": 3, "successThreshold": 1}
                container["readinessProbe"] = dict(defaulted_probe)
                container["livenessProbe"] = dict(defaulted_probe)
                pods[name]["spec"]["tolerations"].append({
                    "key": "node.kubernetes.io/memory-pressure",
                    "operator": "Exists", "effect": "NoSchedule"})
            pods[name]["status"]["containerStatuses"] = [{
                "name": container["name"], "image": "sha256:runtime-config-digest",
                "containerID": "containerd://" + name,
                "imageID": "harbor.example/image@sha256:runtime-platform-digest"}]
        firewall = {"metadata": {"uid": "daemonset-uid", "generation": 2},
                    "status": {"observedGeneration": 2, "desiredNumberScheduled": 1,
                               "updatedNumberScheduled": 1, "numberReady": 1}}
        firewall_pod = {"metadata": {"uid": "firewall-uid", "ownerReferences": [{
                            "apiVersion": "apps/v1", "kind": "DaemonSet",
                            "name": "kube-router-network-policy", "uid": "daemonset-uid",
                            "controller": True, "blockOwnerDeletion": True}]},
                        "spec": {"nodeName": "zimaboard-0",
                                 "containers": [{"image": self.module.FIREWALL_IMAGE}]},
                        "status": {"phase": "Running", "conditions": [
                            {"type": "Ready", "status": "True"}]}}
        policy = json.loads(json.dumps(self.module.EXPECTED_POLICY))
        objects = {
            ("get", "node", "zimaboard-0"): node,
            ("get", "node", self.module.FIXTURE_NODE): server_node,
            ("get", "namespace", self.module.NAMESPACE): namespace,
            ("-n", "kube-system", "get", "daemonset", "kube-router-network-policy"): firewall,
            ("-n", "kube-system", "get", "pods", "-l",
             "app.kubernetes.io/name=kube-router-network-policy"): {"items": [firewall_pod]},
            ("-n", self.module.NAMESPACE, "get", "networkpolicies"): {"items": [policy]},
            ("-n", self.module.NAMESPACE, "get", "pods"): {"items": list(pods.values())},
        }
        for name, pod in pods.items():
            objects[("-n", self.module.NAMESPACE, "get", "pod", name)] = pod
        config = {"activationEnabled": True, "canary": {"node": "zimaboard-0"},
                  "nodeOrder": ["zimaboard-0", "acer"]}
        with patch.object(self.module, "kubernetes_json", side_effect=lambda *args: objects[args]), \
                patch.object(self.module, "inspect_firewall_source", return_value=firewall):
            self.assertEqual(self.module.inspect(config)[0]["metadata"]["uid"], "node-uid")
            pods["npq-allowed"]["spec"]["nodeName"] = "zimaboard-0"
            with self.assertRaisesRegex(ValueError, "fixture identity"):
                self.module.inspect(config)
            pods["npq-allowed"]["spec"]["nodeName"] = self.module.FIXTURE_NODE
            pods["npq-allowed"]["metadata"]["deletionTimestamp"] = "2026-11-01T00:00:00Z"
            with self.assertRaisesRegex(ValueError, "fixture identity"):
                self.module.inspect(config, False)
            del pods["npq-allowed"]["metadata"]["deletionTimestamp"]
            pods["npq-allowed"]["metadata"]["ownerReferences"] = [{
                "kind": "Job", "name": "replacement"}]
            with self.assertRaisesRegex(ValueError, "fixture identity"):
                self.module.inspect(config, False)
            del pods["npq-allowed"]["metadata"]["ownerReferences"]
            pods["npq-allowed"]["spec"]["tolerations"].append({
                "key": self.module.CANARY_KEY, "operator": "Exists",
                "effect": "NoSchedule"})
            with self.assertRaisesRegex(ValueError, "fixture identity"):
                self.module.inspect(config)
            pods["npq-allowed"]["spec"]["tolerations"].pop()
            server_node["status"]["conditions"][0]["status"] = "False"
            with self.assertRaisesRegex(ValueError, "fixture Node"):
                self.module.inspect(config)
            server_node["status"]["conditions"][0]["status"] = "True"
            pods["npq-allowed"]["spec"]["containers"][0]["readinessProbe"]["periodSeconds"] = 1
            with self.assertRaisesRegex(ValueError, "fixture identity"):
                self.module.inspect(config)
            pods["npq-allowed"]["spec"]["containers"][0]["readinessProbe"]["periodSeconds"] = 10
            objects[("-n", self.module.NAMESPACE, "get", "pods")]["items"].append({
                "metadata": {"name": "foreign"}})
            with self.assertRaisesRegex(ValueError, "foreign or missing Pods"):
                self.module.inspect(config)
            objects[("-n", self.module.NAMESPACE, "get", "pods")]["items"].pop()
            objects[("-n", self.module.NAMESPACE, "get", "networkpolicies")]["items"].append(
                {"kind": "NetworkPolicy", "metadata": {"name": "foreign"}})
            with self.assertRaises(ValueError):
                self.module.inspect(config)
            objects[("-n", self.module.NAMESPACE, "get", "networkpolicies")]["items"].pop()
            node["spec"]["taints"] = []
            with self.assertRaisesRegex(ValueError, "taint"):
                self.module.inspect(config)
            node["spec"]["taints"] = [{"key": self.module.CANARY_KEY,
                                         "value": "true", "effect": "NoSchedule"}]
            firewall["status"]["updatedNumberScheduled"] = 0
            with self.assertRaisesRegex(ValueError, "firewall is not ready"):
                self.module.inspect(config)
            firewall["status"]["updatedNumberScheduled"] = 1
            firewall_pod["metadata"]["ownerReferences"][0]["uid"] = "foreign"
            with self.assertRaisesRegex(ValueError, "firewall is not ready"):
                self.module.inspect(config)
            firewall_pod["metadata"]["ownerReferences"][0]["uid"] = "daemonset-uid"
            client = pods["npq-client"]["spec"]
            for field, value in (("automountServiceAccountToken", True),
                                 ("hostNetwork", True),
                                 ("nodeSelector", {}),
                                 ("volumes", [{"hostPath": {"path": "/"}}]),
                                 ("initContainers", [{"name": "foreign"}])):
                with self.subTest(field=field):
                    original = client.get(field)
                    client[field] = value
                    with self.assertRaisesRegex(ValueError, "fixture identity"):
                        self.module.inspect(config)
                    if original is None:
                        del client[field]
                    else:
                        client[field] = original
            container = client["containers"][0]
            original = container["securityContext"]["allowPrivilegeEscalation"]
            container["securityContext"]["allowPrivilegeEscalation"] = True
            with self.assertRaisesRegex(ValueError, "fixture identity"):
                self.module.inspect(config)
            container["securityContext"]["allowPrivilegeEscalation"] = original
            client["containers"][0]["resources"]["limits"]["memory"] = "128Mi"
            with self.assertRaisesRegex(ValueError, "fixture identity"):
                self.module.inspect(config)
            client["containers"][0]["resources"] = json.loads(
                json.dumps(self.module.FIXTURE_RESOURCES))
            pods["npq-denied"]["status"]["containerStatuses"][0]["imageID"] = ""
            with self.assertRaisesRegex(ValueError, "fixture identity"):
                self.module.inspect(config)
            pods["npq-denied"]["status"]["containerStatuses"][0]["imageID"] = (
                "harbor.example/image@sha256:runtime-platform-digest")
            for name in ("npq-client", "npq-allowed", "npq-denied"):
                fixture = pods[name]["spec"]["containers"][0]
                with self.subTest(name=name, field="command"):
                    original = fixture["command"]
                    fixture["command"] = ["/usr/bin/python3", "-c", "print('npq-ok')"]
                    with self.assertRaisesRegex(ValueError, "fixture identity"):
                        self.module.inspect(config)
                    fixture["command"] = original
                with self.subTest(name=name, field="args"):
                    fixture["args"] = ["--ignore-client"]
                    with self.assertRaisesRegex(ValueError, "fixture identity"):
                        self.module.inspect(config)
                    del fixture["args"]
                for field, value in (("runAsNonRoot", False), ("runAsUser", 0),
                                     ("seccompProfile", {"type": "Unconfined"})):
                    with self.subTest(name=name, field=field):
                        fixture["securityContext"][field] = value
                        with self.assertRaisesRegex(ValueError, "fixture identity"):
                            self.module.inspect(config)
                        del fixture["securityContext"][field]
            client["containers"].append({"name": "foreign", "image": self.module.IMAGE})
            with self.assertRaisesRegex(ValueError, "fixture identity"):
                self.module.inspect(config)

    def test_live_firewall_source_rejects_router_or_rbac_drift(self):
        name = "kube-router-network-policy"
        role = {"metadata": {"name": name}, "rules": [
            {"apiGroups": [""], "resources": ["namespaces", "pods", "services", "nodes", "endpoints"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": ["networking.k8s.io"], "resources": ["networkpolicies"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": ["discovery.k8s.io"], "resources": ["endpointslices"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": ["coordination.k8s.io"], "resources": ["leases"],
             "verbs": ["get", "create", "update"]},
        ]}
        template = {"serviceAccountName": name, "hostNetwork": True,
                    "dnsPolicy": "ClusterFirstWithHostNet",
                    "priorityClassName": "system-node-critical",
                    "nodeSelector": {self.module.CANARY_KEY: "true"},
                    "tolerations": [{"key": self.module.CANARY_KEY, "operator": "Equal",
                                     "value": "true", "effect": "NoSchedule"}],
                    "volumes": [{"name": "xtables-lock", "hostPath": {
                        "path": "/run/xtables.lock", "type": "FileOrCreate"}}],
                    "containers": [{"image": self.module.FIREWALL_IMAGE,
                                    "args": sorted(self.module.FIREWALL_FLAGS),
                                    "env": [{"name": "NODE_NAME", "valueFrom": {"fieldRef": {
                                        "fieldPath": "spec.nodeName"}}},
                                            {"name": "POD_NAME", "valueFrom": {"fieldRef": {
                                                "fieldPath": "metadata.name"}}}],
                                    "livenessProbe": {"httpGet": {"host": "127.0.0.1"}},
                                    "readinessProbe": {"httpGet": {"host": "127.0.0.1"}},
                                    "volumeMounts": [{"name": "xtables-lock",
                                                      "mountPath": "/run/xtables.lock"}],
                                    "securityContext": {"privileged": True}}]}
        daemonset = {"metadata": {"name": name, "namespace": "kube-system"},
                     "spec": {"selector": {"matchLabels": {"app.kubernetes.io/name": name}},
                              "template": {"spec": template}}}
        objects = {
            ("-n", "kube-system", "get", "serviceaccount", name):
                {"metadata": {"name": name, "namespace": "kube-system"}},
            ("get", "clusterrole", name): role,
            ("get", "clusterrolebinding", name):
                {"metadata": {"name": name},
                 "roleRef": {"apiGroup": "rbac.authorization.k8s.io",
                             "kind": "ClusterRole", "name": name},
                 "subjects": [{"kind": "ServiceAccount", "name": name,
                               "namespace": "kube-system"}]},
            ("-n", "kube-system", "get", "daemonset", name): daemonset,
        }
        with patch.object(self.module, "kubernetes_json", side_effect=lambda *args: objects[args]):
            self.assertIs(self.module.inspect_firewall_source(), daemonset)
            template["containers"][0]["args"].remove("--run-router=false")
            template["containers"][0]["args"].append("--run-router=true")
            with self.assertRaisesRegex(ValueError, "firewall-only"):
                self.module.inspect_firewall_source()
            template["containers"][0]["args"].remove("--run-router=true")
            template["containers"][0]["args"].append("--run-router=false")
            role["rules"][0]["verbs"].append("update")
            with self.assertRaisesRegex(ValueError, "RBAC"):
                self.module.inspect_firewall_source()

    def test_protected_source_is_required_before_receipt(self):
        with patch.dict(self.module.os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "protected current-main"):
                self.module.require_protected_source()

    def test_traffic_receipt_refuses_same_uid_server_ip_change(self):
        node = {"metadata": {"uid": "z2"}, "status": {"nodeInfo": {"bootID": "z2-boot"}}}
        server = {"metadata": {"uid": "z1"}, "status": {"nodeInfo": {"bootID": "z1-boot"}}}
        pods = {"npq-allowed": {"metadata": {"uid": "same-uid"},
                                "spec": {"nodeName": self.module.FIXTURE_NODE},
                                "status": {"podIP": "10.42.0.2",
                                           "containerStatuses": [{
                                               "containerID": "containerd://same",
                                               "imageID": "repo@sha256:" + "1" * 64}]}}}
        after = json.loads(json.dumps(pods))
        after["npq-allowed"]["status"]["podIP"] = "10.42.0.3"
        firewall = {"metadata": {"uid": "enforcer-uid"}}
        inspections = iter(((node, server, pods, firewall, "policy"),
                            (node, server, after, firewall, "policy")))
        outputs = []
        with patch.object(self.module, "require_protected_source", return_value="a" * 40), \
                patch.object(self.module, "inspect", side_effect=lambda *_: next(inspections)), \
                patch.object(self.module, "traffic_matrix", return_value=[]), \
                patch.object(self.module, "private_output", side_effect=lambda _path, record:
                             outputs.append(record)), \
                patch.object(self.module.runpy, "run_path", return_value={
                    "validate_config": lambda value: value}), \
                patch.object(sys, "argv", ["qualification", "--output", "/tmp/probe.json"]):
            self.assertEqual(self.module.main(), 1)
        self.assertEqual([record["result"] for record in outputs], ["traffic-probe-failed"])
        self.assertIn("identity changed", outputs[0]["diagnostic"])

    def test_receipt_is_private_exclusive_and_not_a_lifecycle_pass(self):
        node = {"metadata": {"name": "zimaboard-0", "uid": "node-uid"},
                "status": {"nodeInfo": {"bootID": "boot-id"}}}
        server_node = {"metadata": {"name": self.module.FIXTURE_NODE,
                                    "uid": "server-node-uid"},
                       "status": {"nodeInfo": {"bootID": "server-boot-id"}}}
        pods = {"npq-client": {"metadata": {"uid": "client-uid"},
                               "spec": {"nodeName": "zimaboard-0"},
                               "status": {"podIP": "10.42.0.2",
                                          "containerStatuses": [{
                                              "containerID": "containerd://client",
                                              "imageID": "repo@sha256:" + "1" * 64}]}}}
        firewall = {"metadata": {"uid": "firewall-uid"}}
        receipt = self.module.traffic_receipt(
            "a" * 40, node, server_node, pods, firewall, "b" * 64,
            [{"permitted": False}])
        self.assertEqual(receipt["fixtureNodeUid"], "server-node-uid")
        self.assertEqual(receipt["fixturePodNodes"], {"npq-client": "zimaboard-0"})
        self.assertEqual(receipt["fixturePodIps"], {"npq-client": "10.42.0.2"})
        after = json.loads(json.dumps(pods))
        after["npq-client"]["status"]["podIP"] = "10.42.0.3"
        self.assertNotEqual(self.module.fixture_identity(pods),
                            self.module.fixture_identity(after))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.json"
            self.module.private_output(path, receipt)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text())["result"],
                             "traffic-probe-passed-lifecycle-unverified")
            self.assertEqual(receipt["unverifiedLifecycleScenarios"], [
                "cold-bootstrap", "first-application-packet", "enforcer-graceful-stop",
                "enforcer-crash-restart", "api-loss", "policy-change-and-conntrack",
                "pod-reschedule-and-ip-reuse", "cold-node-reboot", "ipv6-absence"])
            self.assertNotIn("verified", receipt)
            with self.assertRaises(ValueError):
                self.module.private_output(path, {})


if __name__ == "__main__":
    unittest.main()
