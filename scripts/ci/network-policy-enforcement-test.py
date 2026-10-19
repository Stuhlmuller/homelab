#!/usr/bin/env python3
"""Guard the disabled firewall-only kube-router source before live qualification."""

import json
import subprocess
import unittest
from pathlib import Path


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
    return [json.loads(line) for line in parsed.stdout.splitlines()]


class FirewallSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.objects = rendered_objects()
        cls.by_kind = {item["kind"]: item for item in cls.objects}

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
        self.assertEqual({item["name"] for item in container["env"]},
                         {"NODE_NAME", "POD_NAME"})
        self.assertEqual(pod["serviceAccountName"], "kube-router-network-policy")

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

    def test_qualification_fixtures_stay_separate_and_tainted(self):
        self.assertEqual(subprocess.check_output(
            ["kubectl", "kustomize", str(SOURCE / "canary")], text=True), "")
        fixtures = rendered_objects(SOURCE / "canary" / "fixtures.yaml")
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
            self.assertEqual(spec["nodeSelector"], {
                "homelab.stinkyboi.com/network-policy-canary": "true"})
            self.assertEqual(spec["tolerations"], [{
                "key": "homelab.stinkyboi.com/network-policy-canary",
                "operator": "Equal", "value": "true", "effect": "NoSchedule"}])
            self.assertFalse(spec["automountServiceAccountToken"])
            image = spec["containers"][0]["image"]
            self.assertIn("harbor.stinkyboi.com/mirror/cgr.dev/chainguard/python:", image)
            self.assertIn("@sha256:", image)
        policy, = (item for item in fixtures if item["kind"] == "NetworkPolicy")
        self.assertEqual(policy["spec"]["podSelector"], {"matchLabels": {"role": "client"}})
        self.assertEqual(policy["spec"]["policyTypes"], ["Egress"])
        rule, = policy["spec"]["egress"]
        self.assertEqual(rule["to"], [{"podSelector": {"matchLabels": {"role": "allowed"}}}])
        self.assertEqual({(port["protocol"], port["port"]) for port in rule["ports"]},
                         {("TCP", 8080), ("UDP", 8080)})
        for item in fixtures:
            if item["kind"] == "Pod" and item["metadata"]["name"] != "npq-client":
                self.assertEqual({(port["protocol"], port["containerPort"])
                                  for port in item["spec"]["containers"][0]["ports"]},
                                 {("TCP", 8080), ("UDP", 8080), ("TCP", 9090)})


if __name__ == "__main__":
    unittest.main()
