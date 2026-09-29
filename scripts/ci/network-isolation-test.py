#!/usr/bin/env python3
"""Offline contract/negative tests. These do not simulate Linux packet filtering."""

import copy
import importlib.util
import ipaddress
import json
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "clusters/homelab/platform/network-isolation-candidate"
SPEC = importlib.util.spec_from_file_location(
    "probe", ROOT / "scripts/network-isolation-probe.py"
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def documents(path):
    return [x for x in yaml.safe_load_all(path.read_text()) if isinstance(x, dict)]


def all_policies():
    return [
        d
        for p in (ROOT / "clusters").rglob("*.yaml")
        if "candidate" not in str(p)
        for d in documents(p)
        if d.get("kind") == "NetworkPolicy"
    ] + [
        d
        for p in (CANDIDATE / "policies").glob("*.yaml")
        for d in documents(p)
        if d.get("kind") == "NetworkPolicy"
    ]


def permitted(policies, ns, labels, dest_ns, dest_labels, ip, port, protocol="TCP"):
    selected = [
        p
        for p in policies
        if p["metadata"]["namespace"] == ns
        and "Egress" in p["spec"]["policyTypes"]
        and probe.select(p["spec"]["podSelector"], labels)
    ]
    if not selected:
        return True
    for policy in selected:
        for rule in policy["spec"].get("egress", []):
            if rule.get("ports") and not any(
                p.get("protocol", "TCP") == protocol and p["port"] == port
                for p in rule["ports"]
            ):
                continue
            if not rule.get("to"):
                return True
            for peer in rule["to"]:
                if "ipBlock" in peer:
                    b = peer["ipBlock"]
                    addr = ipaddress.ip_address(ip)
                    if addr in ipaddress.ip_network(b["cidr"]) and not any(
                        addr in ipaddress.ip_network(c) for c in b.get("except", [])
                    ):
                        return True
                elif (
                    probe.select(
                        peer["namespaceSelector"],
                        {"kubernetes.io/metadata.name": dest_ns},
                    )
                    if "namespaceSelector" in peer
                    else ns == dest_ns
                ) and probe.select(peer.get("podSelector", {}), dest_labels):
                    return True
    return False


class Contracts(unittest.TestCase):
    def test_inventory_matches_all_source_policies(self):
        expected = json.loads((CANDIDATE / "policy-inventory.json").read_text())
        actual = []
        for p in sorted((ROOT / "clusters").rglob("*.yaml")):
            if "candidate" in str(p):
                continue
            for d in documents(p):
                if d.get("kind") == "NetworkPolicy":
                    actual.append(
                        {
                            "path": str(p.relative_to(ROOT)),
                            "namespace": d["metadata"]["namespace"],
                            "name": d["metadata"]["name"],
                            "spec": d["spec"],
                        }
                    )
        self.assertEqual(
            actual, expected, "Policy drift requires inventory + additive audit"
        )

    def test_engine_is_policy_only(self):
        spec = documents(CANDIDATE / "engine/daemonset.yaml")[0]["spec"]["template"][
            "spec"
        ]
        c = spec["containers"][0]
        for flag in [
            "--run-router=false",
            "--run-service-proxy=false",
            "--run-loadbalancer=false",
            "--run-firewall=true",
            "--enable-cni=false",
        ]:
            self.assertIn(flag, c["args"])
        self.assertNotIn("initContainers", spec)
        self.assertFalse(spec.get("hostPID", False))
        self.assertEqual(
            {v["hostPath"]["path"] for v in spec["volumes"]},
            {"/lib/modules", "/run/xtables.lock"},
        )
        self.assertIn("@sha256:", c["image"])
        role = documents(CANDIDATE / "engine/rbac.yaml")[1]
        for rule in role["rules"]:
            self.assertEqual(rule["verbs"], ["get", "list", "watch"])

    def test_not_registered_and_no_auto_sync(self):
        self.assertNotIn(
            "network-isolation-candidate",
            (ROOT / "IaC/terragrunt.stack.hcl").read_text(),
        )
        for app in documents(CANDIDATE / "applications.yaml"):
            self.assertNotIn("automated", app["spec"]["syncPolicy"])
            self.assertEqual(app["spec"]["source"]["targetRevision"], "main")

    def test_effective_signing_allowlist(self):
        policies = all_policies()
        labels = {
            "app.kubernetes.io/name": "harbor-image-signing",
            "app.kubernetes.io/part-of": "harbor",
        }

        def allowed(ns, dst, ip, port, protocol="TCP"):
            return permitted(policies, "harbor", labels, ns, dst, ip, port, protocol)

        self.assertTrue(
            allowed("istio-system", {"app": "istio-ingressgateway"}, "10.244.0.10", 443)
        )
        self.assertFalse(
            allowed(
                "istio-system", {"app": "istio-ingressgateway"}, "10.244.0.10", 8443
            )
        )
        self.assertFalse(allowed("istio-system", {"app": "other"}, "10.244.0.11", 8443))
        for proto in ["TCP", "UDP"]:
            self.assertTrue(
                allowed(
                    "kube-system", {"k8s-app": "kube-dns"}, "10.244.0.12", 53, proto
                )
            )
        for ip in [
            "1.1.1.1",
            "10.1.0.2",
            "10.1.0.199",
            "100.100.100.100",
            "169.254.169.254",
            "2606:4700:4700::1111",
        ]:
            self.assertFalse(allowed("", {}, ip, 443))
        self.assertFalse(
            allowed(
                "harbor", {"app": "harbor", "component": "nginx"}, "10.244.0.13", 8080
            )
        )

    def test_effective_agent_dependencies_and_denials(self):
        policies = all_policies()
        for name in ["openclaw", "multica-runtime"]:

            def allowed(ns, labels, ip, port, proto="TCP", name=name):
                return permitted(
                    policies,
                    "ai",
                    {"app.kubernetes.io/name": name},
                    ns,
                    labels,
                    ip,
                    port,
                    proto,
                )

            self.assertTrue(allowed("", {}, "1.1.1.1", 443))
            self.assertFalse(allowed("", {}, "1.1.1.1", 80))
            self.assertFalse(allowed("", {}, "1.1.1.1", 53, "UDP"))
            for ip in [
                "10.1.0.2",
                "10.1.0.199",
                "172.16.0.1",
                "192.168.0.1",
                "100.64.0.1",
                "169.254.169.254",
                "127.0.0.1",
                "10.244.0.55",
                "fd00::1",
                "2606:4700::1111",
            ]:
                self.assertFalse(allowed("", {}, ip, 443))
            self.assertTrue(
                allowed("kube-system", {"k8s-app": "kube-dns"}, "10.244.0.3", 53)
            )
            self.assertFalse(
                allowed("kube-system", {"k8s-app": "evil"}, "10.244.0.4", 53)
            )
            self.assertEqual(
                allowed(
                    "ai", {"app.kubernetes.io/name": "litellm"}, "10.244.0.5", 15008
                ),
                name == "openclaw",
            )
            self.assertEqual(
                allowed(
                    "monitoring",
                    {"app.kubernetes.io/name": "grafana"},
                    "10.244.0.6",
                    3000,
                ),
                name == "openclaw",
            )
            self.assertEqual(
                allowed(
                    "ai",
                    {
                        "app.kubernetes.io/name": "multica",
                        "app.kubernetes.io/instance": "multica",
                        "app.kubernetes.io/component": "backend",
                    },
                    "10.244.0.7",
                    15008,
                ),
                name == "multica-runtime",
            )

    def test_recovery_and_transition_union(self):
        policies = all_policies()
        for ns, name in [
            ("isolation-recovery-probe", "isolation-recovery"),
            ("media", "media-postgres-restore"),
        ]:
            for ip in ["10.1.0.2", "1.1.1.1", "fd00::1"]:
                self.assertFalse(
                    permitted(
                        policies, ns, {"app.kubernetes.io/name": name}, "", {}, ip, 443
                    )
                )
        self.assertTrue(
            permitted(
                policies,
                "octelium-public",
                {"app.kubernetes.io/name": "cloudflared"},
                "",
                {},
                "10.1.0.199",
                6443,
            )
        )
        # Demonstrate the actual additive hazard: a later broad allow wins.
        weakened = policies + documents(CANDIDATE / "rollback/allow.yaml")
        self.assertTrue(
            permitted(
                weakened,
                "harbor",
                {"app.kubernetes.io/name": "harbor-image-signing"},
                "",
                {},
                "1.1.1.1",
                443,
            )
        )


class Harness(unittest.TestCase):
    def setUp(self):
        self.matrix = json.loads(
            (ROOT / "scripts/config/network-isolation-matrix.example.json").read_text()
        )
        for t in self.matrix["targets"]:
            if t["host"].startswith("REPLACE"):
                t["host"] = "10.244.0.10"
        self.inventory = {
            "nodes": [
                {"metadata": {"name": "acer"}, "spec": {"podCIDRs": ["10.244.0.0/24"]}}
            ],
            "namespaces": [
                {
                    "metadata": {
                        "name": "ai",
                        "labels": {"istio.io/dataplane-mode": "ambient"},
                    }
                },
                {"metadata": {"name": "harbor"}},
            ],
            "services": [],
            "deployments": [
                {
                    "metadata": {"name": n, "namespace": "ai"},
                    "spec": {
                        "template": {
                            "metadata": {"labels": {"app.kubernetes.io/name": n}},
                            "spec": {"serviceAccountName": n},
                        }
                    },
                }
                for n in ["openclaw", "multica-runtime"]
            ],
        }
        _, self.plan = probe.render(self.inventory, self.matrix, "first")
        self.records = []
        for source in probe.SOURCES:
            for rnd in ["first", "replacement"]:
                self.records.append(
                    {
                        "source": source,
                        "node": "acer",
                        "round": rnd,
                        "identity": self.plan["identities"][source],
                        "pod_uid": source + rnd,
                        "matrix_hash": probe.digest(self.matrix),
                        "results": {
                            t["id"]: (
                                "reachable"
                                if source == "control" or t["expect"][source] == "allow"
                                else "rejected"
                            )
                            for t in self.matrix["targets"]
                        },
                    }
                )

    def test_synthetic_success_both_rounds(self):
        self.assertIn("Transport matrix passed", probe.verify(self.plan, self.records))

    def test_dead_control_cannot_prove_deny(self):
        self.records[-1]["results"]["forbidden-pod"] = "rejected"
        with self.assertRaises(ValueError):
            probe.verify(self.plan, self.records)

    def test_missing_replacement(self):
        with self.assertRaises(ValueError):
            probe.verify(self.plan, self.records[:-1])

    def test_reused_uid(self):
        self.records[1]["pod_uid"] = self.records[0]["pod_uid"]
        with self.assertRaises(ValueError):
            probe.verify(self.plan, self.records)

    def test_resolution_failure_not_denial(self):
        self.records[0]["results"]["forbidden-pod"] = "error:dns"
        with self.assertRaises(ValueError):
            probe.verify(self.plan, self.records)

    def test_identity_or_matrix_drift(self):
        for field in ["identity", "matrix_hash"]:
            records = copy.deepcopy(self.records)
            records[0][field] = "wrong"
            with self.assertRaises(ValueError):
                probe.verify(self.plan, records)

    def test_reachable_negative_fails(self):
        self.records[0]["results"]["forbidden-pod"] = "reachable"
        with self.assertRaises(ValueError):
            probe.verify(self.plan, self.records)

    def test_dual_stack_fails_closed(self):
        self.inventory["nodes"][0]["spec"]["podCIDRs"].append("fd00::/64")
        with self.assertRaises(ValueError):
            probe.render(self.inventory, self.matrix, "first")

    def test_exact_identity_without_secret_volumes_or_ready_endpoints(self):
        docs, _ = probe.render(self.inventory, self.matrix, "first")
        for job in [d for d in docs if d["kind"] == "Job"]:
            spec = job["spec"]["template"]["spec"]
            self.assertFalse(spec["automountServiceAccountToken"])
            self.assertNotIn("hostNetwork", spec)
            self.assertEqual(spec["volumes"][0].keys(), {"name", "configMap"})
            self.assertIn(
                "raise SystemExit(1)",
                spec["containers"][0]["readinessProbe"]["exec"]["command"],
            )
        self.inventory["services"] = [
            {
                "metadata": {"namespace": "ai"},
                "spec": {
                    "selector": {"app.kubernetes.io/name": "openclaw"},
                    "publishNotReadyAddresses": True,
                },
            }
        ]
        with self.assertRaises(ValueError):
            probe.render(self.inventory, self.matrix, "first")

    def test_unresolved_targets_and_secondary_networks(self):
        self.matrix["targets"][0]["host"] = "REPLACE_ME"
        with self.assertRaises(ValueError):
            probe.validate_matrix(self.matrix)
        self.matrix["targets"][0]["host"] = "10.244.0.10"
        self.inventory["deployments"][0]["spec"]["template"]["metadata"][
            "annotations"
        ] = {"k8s.v1.cni.cncf.io/networks": "escape"}
        with self.assertRaises(ValueError):
            probe.render(self.inventory, self.matrix, "first")


class RolloutGuards(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "rollout", ROOT / "scripts/network-isolation-rollout.py"
        )
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_preview_has_no_subprocess_or_mutation(self):
        import contextlib
        import io
        from unittest.mock import patch

        with (
            patch("sys.argv", ["rollout", "engine"]),
            patch.object(self.module.subprocess, "check_output") as read,
            patch.object(self.module.subprocess, "run") as mutate,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.module.main()
        read.assert_not_called()
        mutate.assert_not_called()

    def test_wrong_commit_and_dirty_tree_stop_before_mutation(self):
        import contextlib
        import io
        from unittest.mock import patch

        for outputs, approved in [
            (["abc\n", "abc refs/heads/main\n"], "wrong"),
            (["abc\n", "abc refs/heads/main\n", " M changed\n"], "abc"),
        ]:
            with (
                patch(
                    "sys.argv",
                    ["rollout", "engine", "--execute", "--approved-commit", approved],
                ),
                patch.object(
                    self.module.subprocess, "check_output", side_effect=outputs
                ),
                patch.object(self.module.subprocess, "run") as mutate,
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                self.module.main()
            mutate.assert_not_called()

    def test_approved_sync_pins_revision(self):
        import contextlib
        import io
        from unittest.mock import patch

        with (
            patch(
                "sys.argv",
                ["rollout", "policies", "--execute", "--approved-commit", "abc"],
            ),
            patch.object(
                self.module.subprocess,
                "check_output",
                side_effect=["abc\n", "abc refs/heads/main\n", ""],
            ),
            patch.object(self.module.subprocess, "run") as commands,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.module.main()
        command = commands.call_args_list[-1].args[0]
        self.assertEqual(command[-2:], ["--revision", "abc"])
        self.assertNotIn("--prune", command)

    def test_unsynced_policy_blocks_engine(self):
        import contextlib
        import io
        from unittest.mock import patch

        outputs = [
            "abc\n",
            "abc refs/heads/main\n",
            "",
            json.dumps(
                {
                    "status": {
                        "sync": {"status": "OutOfSync", "revision": "abc"},
                        "health": {"status": "Healthy"},
                    }
                }
            ),
        ]
        with (
            patch(
                "sys.argv",
                ["rollout", "engine", "--execute", "--approved-commit", "abc"],
            ),
            patch.object(self.module.subprocess, "check_output", side_effect=outputs),
            patch.object(self.module.subprocess, "run") as commands,
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            self.module.main()
        self.assertEqual(len(commands.call_args_list), 1)
        self.assertEqual(commands.call_args_list[0].args[0][0], "kustomize")


if __name__ == "__main__":
    unittest.main()
