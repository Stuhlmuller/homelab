#!/usr/bin/env python3
"""Exercise the Cilium egress audit against exported policy snapshots."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


AUDIT = Path(__file__).resolve().parents[1] / "cilium-egress-audit.py"


class EgressAuditTests(unittest.TestCase):
    def audit(self, rule):
        snapshot = {"kind": "CiliumNetworkPolicy", "metadata": {"name": "sample"},
                    "spec": {"endpointSelector": {}, "egress": [rule]}}
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / "policy.json"
            policy.write_text(json.dumps({"items": [snapshot]}))
            return subprocess.run([sys.executable, "-I", str(AUDIT), str(policy)],
                                  capture_output=True, text=True, check=False)

    def test_default_deny_rule_passes(self):
        result = self.audit({})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_port_only_grant_requires_a_destination(self):
        result = self.audit({"toPorts": [{"ports": [{"port": "443", "protocol": "TCP"}]}]})
        self.assertEqual(result.returncode, 1)
        self.assertIn("rule has no explicit destination", result.stderr)

    def test_cluster_mesh_is_broad(self):
        result = self.audit({"toEntities": ["cluster-mesh"]})
        self.assertEqual(result.returncode, 1)
        self.assertIn("broad destination entity cluster-mesh", result.stderr)

    def test_reserved_world_selectors_are_broad(self):
        for selector in (
            {"matchLabels": {"reserved:world": ""}},
            {"matchExpressions": [{"key": "reserved:world-ipv4", "operator": "Exists"}]},
            {"matchExpressions": [{"key": "reserved:world-ipv6", "operator": "In", "values": [""]}]},
        ):
            with self.subTest(selector=selector):
                result = self.audit({"toEndpoints": [selector]})
                self.assertEqual(result.returncode, 1)
                self.assertIn("toEndpoints selects broad reserved identity reserved:world", result.stderr)

    def test_application_label_remains_an_explicit_destination(self):
        result = self.audit({"toEndpoints": [{"matchLabels": {"app": "world"}}]})
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
