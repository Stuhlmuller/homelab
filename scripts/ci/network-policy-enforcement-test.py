#!/usr/bin/env python3
"""Guard retained firewall-only source across reviewed GitOps phases."""

import json
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "clusters/homelab/platform/network-policy"
DIGEST = "64da9a538d29e13780e256ce3897a52932a68657793bef009063bbeb2762146a"
FLAGS = {
    "--run-router=false", "--run-service-proxy=false",
    "--run-loadbalancer=false", "--run-firewall=true", "--enable-cni=false",
    "--netpol-default-deny=true", "--use-nftables-for-netpol=false",
    "--enable-ipv4=true", "--enable-ipv6=false",
    "--health-addr=127.0.0.1",
}
EMPTY_KUST = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n"
ENFORCER_KUST = ("apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
                 "resources:\n  - daemonset.yaml\n")
FIXTURES_KUST = ("apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
                 "resources:\n  - fixtures.yaml\n")
QUALIFICATION_SPEC = importlib.util.spec_from_file_location(
    "network_policy_qualification", ROOT / "scripts/network-policy-qualification.py"
)
qualification = importlib.util.module_from_spec(QUALIFICATION_SPEC)
QUALIFICATION_SPEC.loader.exec_module(qualification)


def rendered_objects(path=SOURCE):
    if path.is_file():
        source = path.read_text()
    else:
        rendered = subprocess.run(
            ["kubectl", "kustomize", str(path)], capture_output=True,
            text=True, check=True, timeout=30,
        )
        source = rendered.stdout
    parsed = subprocess.run(
        ["yq", "-o=json", "-I=0", "."], input=source,
        capture_output=True, text=True, check=True, timeout=30,
    )
    return [item for line in parsed.stdout.splitlines()
            if (item := json.loads(line)) is not None]


def canonical_objects(items):
    return sorted(json.dumps(item, sort_keys=True) for item in items)


class FirewallSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # This retained source remains reviewable after GitOps prunes its overlay.
        cls.objects = rendered_objects(SOURCE / "daemonset.yaml")
        cls.by_kind = {item["kind"]: item for item in cls.objects}

    def test_enforcer_overlay_matches_reviewed_source_phase(self):
        source = (SOURCE / "kustomization.yaml").read_text()
        self.assertIn(source, {ENFORCER_KUST, EMPTY_KUST})
        rendered = rendered_objects()
        if source == ENFORCER_KUST:
            self.assertEqual(canonical_objects(rendered), canonical_objects(self.objects))
        else:
            self.assertEqual(rendered, [])

    def test_exact_owned_resources_and_rbac(self):
        self.assertEqual(set(self.by_kind), {
            "ServiceAccount", "ClusterRole", "ClusterRoleBinding", "DaemonSet"})
        for item in self.objects:
            self.assertEqual(item["metadata"]["name"], "kube-router-network-policy")
        role = self.by_kind["ClusterRole"]["rules"]
        self.assertEqual({(tuple(rule["apiGroups"]), tuple(rule["resources"]),
                           tuple(rule["verbs"])) for rule in role}, {
            (("",), ("namespaces", "pods", "services", "nodes", "endpoints"),
             ("get", "list", "watch")),
            (("networking.k8s.io",), ("networkpolicies",), ("get", "list", "watch")),
            (("discovery.k8s.io",), ("endpointslices",), ("get", "list", "watch")),
            (("coordination.k8s.io",), ("leases",), ("get", "create", "update")),
        })

    def test_firewall_only_and_no_cni_host_ownership(self):
        pod = self.by_kind["DaemonSet"]["spec"]["template"]["spec"]
        container, = pod["containers"]
        self.assertEqual(set(container["args"]), FLAGS)
        self.assertEqual(len(container["args"]), len(FLAGS))
        self.assert_firewall_entrypoint(container)
        self.assertEqual(container["livenessProbe"]["httpGet"]["host"], "127.0.0.1")
        self.assertEqual(container["readinessProbe"]["httpGet"]["host"], "127.0.0.1")
        self.assertNotIn("initContainers", pod)
        self.assertNotIn("hostPID", pod)
        self.assertNotIn("hostIPC", pod)
        self.assertTrue(pod["hostNetwork"])
        self.assertEqual(pod["volumes"], [{
            "name": "xtables-lock", "hostPath": {
                "path": "/run/xtables.lock", "type": "FileOrCreate"}}])
        self.assertEqual(container["volumeMounts"], [{
            "name": "xtables-lock", "mountPath": "/run/xtables.lock"}])
        self.assertEqual(pod["serviceAccountName"], "kube-router-network-policy")

    def assert_firewall_entrypoint(self, container):
        self.assertNotIn("command", container)
        self.assertNotIn("envFrom", container)
        self.assertEqual(container["env"], [
            {"name": "NODE_NAME", "valueFrom": {"fieldRef": {"fieldPath": "spec.nodeName"}}},
            {"name": "POD_NAME", "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}}},
        ])

    def test_rejects_firewall_entrypoint_and_environment_overrides(self):
        container, = self.by_kind["DaemonSet"]["spec"]["template"]["spec"]["containers"]
        for override in (
            {"command": ["/bin/sh", "-c", "unreviewed"]},
            {"envFrom": [{"configMapRef": {"name": "unreviewed"}}]},
            {"env": [{"name": "NODE_NAME", "value": "unreviewed"},
                     container["env"][1]]},
        ):
            with self.subTest(override=override), self.assertRaises(AssertionError):
                self.assert_firewall_entrypoint({**container, **override})

    def test_unadmitted_canary_and_paired_image(self):
        pod = self.by_kind["DaemonSet"]["spec"]["template"]["spec"]
        self.assertEqual(pod["nodeSelector"], {
            "homelab.stinkyboi.com/network-policy-canary": "true"})
        self.assertEqual(pod["tolerations"], [{
            "key": "homelab.stinkyboi.com/network-policy-canary",
            "operator": "Equal", "value": "true", "effect": "NoSchedule"}])
        image = pod["containers"][0]["image"]
        self.assertEqual(image, "harbor.stinkyboi.com/mirror/docker.io/"
                         f"cloudnativelabs/kube-router:{DIGEST}@sha256:{DIGEST}")
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
        self.assertIn({"source": f"docker.io/cloudnativelabs/kube-router:v2.11.1@sha256:{DIGEST}"},
                      catalog["images"])

    def test_qualification_fixtures_keep_split_placement(self):
        source = (SOURCE / "canary" / "kustomization.yaml").read_text()
        self.assertIn(source, {EMPTY_KUST, FIXTURES_KUST})
        fixtures = rendered_objects(SOURCE / "canary" / "fixtures.yaml")
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory)
            (candidate / "fixtures.yaml").write_bytes(
                (SOURCE / "canary" / "fixtures.yaml").read_bytes())
            (candidate / "kustomization.yaml").write_text(FIXTURES_KUST)
            self.assertEqual(canonical_objects(rendered_objects(candidate)),
                             canonical_objects(fixtures))
        rendered = rendered_objects(SOURCE / "canary")
        self.assertEqual(canonical_objects(rendered),
                         canonical_objects(fixtures if source == FIXTURES_KUST else []))
        self.assertEqual({(item["kind"], item["metadata"]["name"]) for item in fixtures}, {
            ("Namespace", "network-policy-canary"),
            ("Pod", "npq-client"), ("Pod", "npq-allowed"), ("Pod", "npq-denied"),
            ("NetworkPolicy", "npq-client-egress"),
        })
        self.assertFalse(any(item["kind"] in {"Pod", "NetworkPolicy"} for item in self.objects))
        for item in fixtures:
            if item["kind"] != "Pod":
                continue
            spec = item["spec"]
            if item["metadata"]["name"] == "npq-client":
                self.assertEqual(spec["nodeSelector"], {
                    "homelab.stinkyboi.com/network-policy-canary": "true"})
                self.assertEqual(spec["tolerations"], [{
                    "key": "homelab.stinkyboi.com/network-policy-canary",
                    "operator": "Equal", "value": "true", "effect": "NoSchedule"}])
            else:
                self.assertEqual(spec["nodeSelector"], {
                    "kubernetes.io/hostname": "zimaboard-1"})
                self.assertNotIn("tolerations", spec)
            self.assertFalse(spec["automountServiceAccountToken"])
            image = spec["containers"][0]["image"]
            self.assertIn("harbor.stinkyboi.com/mirror/cgr.dev/chainguard/python:", image)
            self.assertIn("@sha256:", image)
            self.assertEqual(spec["containers"][0]["imagePullPolicy"], "Always")
        policy, = (item for item in fixtures if item["kind"] == "NetworkPolicy")
        self.assertEqual(policy["spec"], qualification.EXPECTED_POLICY["spec"])
        self.assertEqual(policy["spec"]["podSelector"], {"matchLabels": {"role": "client"}})
        self.assertEqual(policy["spec"]["policyTypes"], ["Egress"])
        peer, dns = policy["spec"]["egress"]
        self.assertEqual(peer["to"], [{"podSelector": {"matchLabels": {"role": "allowed"}}}])
        self.assertEqual({(port["protocol"], port["port"]) for port in peer["ports"]},
                         {("TCP", 8080), ("UDP", 8080)})
        self.assertEqual(dns["to"], [{
            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
        }])
        self.assertEqual({(port["protocol"], port["port"]) for port in dns["ports"]},
                         {("TCP", 53), ("UDP", 53)})
        for item in fixtures:
            if item["kind"] == "Pod" and item["metadata"]["name"] != "npq-client":
                self.assertEqual({(port["protocol"], port["containerPort"])
                                  for port in item["spec"]["containers"][0]["ports"]},
                                 {("TCP", 8080), ("UDP", 8080), ("TCP", 9090)})

    def test_dns_matrix_requires_both_transports_and_exact_service(self):
        compile(qualification.DNS_PROBE, "dns-probe", "exec")
        service = {"metadata": {"name": "kube-dns", "namespace": "kube-system"},
                   "spec": {"clusterIP": "10.96.0.10", "ipFamilies": ["IPv4"],
                            "selector": {"k8s-app": "kube-dns"},
                            "ports": [{"protocol": "TCP", "port": 53, "targetPort": 53},
                                      {"protocol": "UDP", "port": 53, "targetPort": 53}]}}
        kubernetes = {"metadata": {"name": "kubernetes", "namespace": "default"},
                      "spec": {"clusterIP": "10.96.0.1", "ipFamilies": ["IPv4"]}}
        objects = {("-n", "kube-system", "get", "service", "kube-dns"): service,
                   ("-n", "default", "get", "service", "kubernetes"): kubernetes}
        with (mock.patch.object(qualification, "kubernetes_json",
                                side_effect=lambda *args: objects[args]),
              mock.patch.object(qualification, "probe_dns", return_value=
                                subprocess.CompletedProcess([], 0, "NPQ_DNS_ALLOWED\n", "")) as probe):
            results = qualification.dns_matrix()
        self.assertEqual([item["protocol"] for item in results], ["TCP", "UDP"])
        self.assertEqual([item["observed"] for item in results],
                         ["NPQ_DNS_ALLOWED", "NPQ_DNS_ALLOWED"])
        self.assertEqual(probe.call_count, 2)
        self.assertEqual({call.args for call in probe.call_args_list}, {
            ("npq-client", "10.96.0.10", "TCP", "10.96.0.1"),
            ("npq-client", "10.96.0.10", "UDP", "10.96.0.1"),
        })
        with (mock.patch.object(qualification, "kubernetes_json",
                                side_effect=lambda *args: objects[args]),
              mock.patch.object(qualification, "probe_dns", side_effect=[
                  subprocess.CompletedProcess([], 0, "NPQ_DNS_ALLOWED\n", ""),
                  subprocess.CompletedProcess([], 7, "", "")])):
            with self.assertRaisesRegex(ValueError, "DNS"):
                qualification.dns_matrix()
        service["spec"]["selector"] = {"k8s-app": "foreign"}
        with mock.patch.object(qualification, "kubernetes_json",
                               side_effect=lambda *args: objects[args]):
            with self.assertRaisesRegex(ValueError, "DNS"):
                qualification.dns_matrix()

    def test_traffic_receipt_includes_both_dns_probes(self):
        pods = {name: {"status": {"podIP": f"10.244.1.{index}"}}
                for index, name in enumerate(("npq-client", "npq-allowed", "npq-denied"), 10)}
        dns = [{"source": "npq-client", "target": "kube-dns", "port": 53,
                "protocol": protocol, "permitted": True, "observed": "NPQ_DNS_ALLOWED"}
               for protocol in ("TCP", "UDP")]
        outcomes = [subprocess.CompletedProcess([], 0 if case[4] else 7,
                    "NPQ_ALLOWED\n" if case[4] else "NPQ_DENIED\n", "")
                    for case in qualification.CASES]
        with (mock.patch.object(qualification, "probe", side_effect=outcomes),
              mock.patch.object(qualification, "dns_matrix", return_value=dns) as checked):
            result = qualification.traffic_matrix(pods)
        checked.assert_called_once_with()
        self.assertEqual(result[-2:], dns)


if __name__ == "__main__":
    unittest.main()
