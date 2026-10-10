"""Synthetic failure cases for offline validation; no cluster or network access."""

import copy
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("istio-upgrade-check.py")
SPEC = importlib.util.spec_from_file_location("istio_check", SCRIPT)
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


class OfflineGateTests(unittest.TestCase):
    def setUp(self):
        self.values = json.loads((check.SPEC / "chart-values.json").read_text())
        self.hold = json.loads((check.SPEC / "hold.json").read_text())

    def test_committed_design_is_valid_but_not_promotable(self):
        check.validate_values(self.values)
        check.validate_hold(self.hold)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--promotion-check"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["promotion"], "BLOCKED")

    def test_shared_values_rejected_for_gateway(self):
        self.values["istio-ingressgateway"]["values"]["cni"] = {}
        with self.assertRaises(ValueError):
            check.validate_values(self.values)

    def test_ignored_legacy_nesting_rejected(self):
        for release, legacy in [("istiod", "pilot"), ("istio-cni", "cni")]:
            with self.subTest(release=release):
                candidate = copy.deepcopy(self.values)
                candidate[release]["values"][legacy] = {"enabled": True}
                with self.assertRaises(ValueError):
                    check.validate_values(candidate)

    def test_missing_gateway_or_wrong_chart_rejected(self):
        self.values.pop("octelium-api-ingressgateway")
        with self.assertRaises(ValueError):
            check.validate_values(self.values)

    def test_hold_cannot_be_enabled_with_boolean(self):
        for field in ["executor_implemented", "promotion_authorized"]:
            candidate = copy.deepcopy(self.hold)
            candidate[field] = True
            with self.assertRaises(ValueError):
                check.validate_hold(candidate)

    def test_self_asserted_receipt_does_not_unlock(self):
        for key in check.EVIDENCE:
            candidate = copy.deepcopy(self.hold)
            candidate["required_evidence"][key].update(
                status="passed", receipt="claimed"
            )
            with self.assertRaises(ValueError):
                check.validate_hold(candidate)

    def test_missing_gate_and_reordered_stages_rejected(self):
        self.hold["required_evidence"].pop("recovery")
        with self.assertRaises(ValueError):
            check.validate_hold(self.hold)
        self.setUp()
        self.hold["stages"] = ["cni", "base", "istiod", "ztunnel", "gateways"]
        with self.assertRaises(ValueError):
            check.validate_hold(self.hold)

    def test_unresolved_target_never_calls_helm(self):
        with patch.object(check.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "missing reviewed chart locks"):
                check.render(Path("helm"), Path("charts"), "1.31.1", self.values, [])
            run.assert_not_called()

    def test_corrupt_archive_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "chart.tgz"
            p.write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                check.verified_archive(p, {"sha256": "0" * 64})

    def test_helm_failure_is_not_retried_with_schema_skip(self):
        lock = [
            {"chart": chart, "version": "1.27.3"}
            for chart in ["base", "istiod", "cni", "ztunnel", "gateway"]
        ]
        failed = subprocess.CompletedProcess([], 1, "", "potential sensitive output")
        with (
            patch.object(check, "verified_archive", return_value=True),
            patch.object(check.subprocess, "run", return_value=failed) as run,
        ):
            with self.assertRaisesRegex(ValueError, "strict Helm validation failed"):
                check.render(Path("helm"), Path("charts"), "1.27.3", self.values, lock)
            self.assertEqual(run.call_count, 1)
            self.assertNotIn("--skip-schema-validation", run.call_args.args[0])

    def test_memory_request_regression_is_rejected(self):
        obj = {
            "kind": "Deployment",
            "metadata": {"name": "istiod"},
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "discovery",
                                "resources": {"requests": {"memory": "2048Mi"}},
                            }
                        ]
                    }
                }
            },
        }
        with self.assertRaisesRegex(ValueError, "memory request"):
            check.semantic_check("istiod", [obj])

    def test_wrong_archive_identity_rejected_even_with_correct_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "chart.tgz"
            content = b"name: base\nversion: 1.28.10\nappVersion: 1.28.10\n"
            with tarfile.open(p, "w:gz") as archive:
                member = tarfile.TarInfo("base/Chart.yaml")
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                check.verified_archive(
                    p,
                    {
                        "chart": "base",
                        "version": "1.27.3",
                        "sha256": check.hashlib.sha256(p.read_bytes()).hexdigest(),
                    },
                )

    def test_successful_render_with_wrong_cni_effect_is_rejected(self):
        obj = {
            "kind": "ConfigMap",
            "metadata": {"name": "istio-cni-config"},
            "data": {"AMBIENT_ENABLED": "true", "AMBIENT_DNS_CAPTURE": "true"},
        }
        with self.assertRaisesRegex(ValueError, "DNS_CAPTURE"):
            check.semantic_check("istio-cni", [obj])

    def test_changed_gateway_exposure_rejected(self):
        obj = {
            "kind": "Service",
            "metadata": {"name": "istio-ingressgateway"},
            "spec": {"type": "LoadBalancer"},
        }
        with self.assertRaisesRegex(ValueError, "exposure changed"):
            check.semantic_check("istio-ingressgateway", [obj])


if __name__ == "__main__":
    unittest.main()
