#!/usr/bin/env python3
"""The public chart fetch can retry without loosening its digest gate."""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).with_name("tailnet-dns-test.py")
SPEC = importlib.util.spec_from_file_location("tailnet_dns_contract", SOURCE)
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


class ChartRetryTest(unittest.TestCase):
    COMMAND = ["helm", "template", "tailnet-dns", CONTRACT.CHART, "--version", "4.0.0",
               "--namespace", "tailnet-dns"]

    def test_recovers_after_transient_registry_failure(self):
        failures = [subprocess.CompletedProcess([], 1, "", "429 PRIVATE_URL") for _ in range(2)]
        success = subprocess.CompletedProcess([], 0, "rendered", CONTRACT.CHART_DIGEST)
        with patch.object(CONTRACT.subprocess, "run", side_effect=[*failures, success]) as run, \
                patch.object(CONTRACT.time, "sleep") as sleep:
            result = CONTRACT.render_pinned_chart(self.COMMAND)
        self.assertEqual(result, "rendered")
        self.assertEqual(run.call_count, 3)
        self.assertEqual([call.args for call in sleep.call_args_list], [(2,), (4,)])

    def test_exhausted_fetch_uses_only_verified_package(self):
        failure = subprocess.CompletedProcess([], 1, "", "403 PRIVATE_URL_TOKEN")
        local = subprocess.CompletedProcess([], 0, "offline render", "")
        with patch.object(CONTRACT.subprocess, "run", side_effect=[failure] * 4 + [local]) as run, \
                patch.object(CONTRACT.time, "sleep") as sleep:
            self.assertEqual(CONTRACT.render_pinned_chart(self.COMMAND), "offline render")
        self.assertEqual(run.call_count, 5)
        self.assertEqual([call.args for call in sleep.call_args_list], [(2,), (4,), (8,)])
        self.assertEqual(run.call_args.args[0], ["helm", "template", "tailnet-dns",
                                                 str(CONTRACT.CHART_PACKAGE), "--namespace", "tailnet-dns"])

    def test_wrong_package_hash_blocks_fallback(self):
        failure = subprocess.CompletedProcess([], 1, "", "403 PRIVATE_URL_TOKEN")
        with tempfile.TemporaryDirectory() as tmp:
            wrong = Path(tmp) / "k8s-gateway-4.0.0.tgz"
            wrong.write_bytes(b"private wrong chart")
            with patch.object(CONTRACT, "CHART_PACKAGE", wrong), \
                    patch.object(CONTRACT.subprocess, "run", return_value=failure) as run, \
                    patch.object(CONTRACT.time, "sleep"):
                with self.assertRaisesRegex(ValueError, "fallback package is missing or changed") as raised:
                    CONTRACT.render_pinned_chart(self.COMMAND)
        self.assertNotIn("PRIVATE_URL_TOKEN", str(raised.exception))
        self.assertEqual(run.call_count, 4)

    def test_catalog_hash_change_blocks_fallback(self):
        failure = subprocess.CompletedProcess([], 1, "", "403 PRIVATE_URL_TOKEN")
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "catalog.json"
            catalog.write_text(json.dumps({"charts": [{"chart": "k8s-gateway", "version": "4.0.0",
                                                     "repository": "codeberg.org/k8s-gateway/charts",
                                                     "sha256": "0" * 64}]}))
            with patch.object(CONTRACT, "CHART_CATALOG", catalog), \
                    patch.object(CONTRACT.subprocess, "run", return_value=failure) as run, \
                    patch.object(CONTRACT.time, "sleep"):
                with self.assertRaisesRegex(ValueError, "catalog hash changed"):
                    CONTRACT.render_pinned_chart(self.COMMAND)
        self.assertEqual(run.call_count, 4)

    def test_failed_exact_package_render_withholds_helm_output(self):
        failure = subprocess.CompletedProcess([], 1, "", "403 PRIVATE_URL_TOKEN")
        with patch.object(CONTRACT.subprocess, "run", return_value=failure) as run, \
                patch.object(CONTRACT.time, "sleep"):
            with self.assertRaisesRegex(ValueError, "exact-package fallback") as raised:
                CONTRACT.render_pinned_chart(self.COMMAND)
        self.assertNotIn("PRIVATE_URL_TOKEN", str(raised.exception))
        self.assertEqual(run.call_count, 5)

    def test_values_or_template_error_cannot_use_fallback(self):
        failure = subprocess.CompletedProcess([], 1, "", "template: private values are invalid")
        with patch.object(CONTRACT.subprocess, "run", return_value=failure) as run, \
                patch.object(CONTRACT.time, "sleep") as sleep:
            with self.assertRaisesRegex(ValueError, "non-fetch") as raised:
                CONTRACT.render_pinned_chart(self.COMMAND)
        self.assertNotIn("private values", str(raised.exception))
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    def test_fetch_timeouts_are_bounded_before_exact_fallback(self):
        timeout = subprocess.TimeoutExpired(self.COMMAND, 20, stderr=b"PRIVATE_TOKEN")
        local = subprocess.CompletedProcess([], 0, "offline render", "")
        with patch.object(CONTRACT.subprocess, "run", side_effect=[timeout] * 4 + [local]) as run, \
                patch.object(CONTRACT.time, "sleep"):
            self.assertEqual(CONTRACT.render_pinned_chart(self.COMMAND), "offline render")
        self.assertEqual(run.call_count, 5)
        self.assertTrue(all(call.kwargs["timeout"] == 20 for call in run.call_args_list))

    def test_successful_oci_render_still_requires_pinned_digest(self):
        rendered = subprocess.CompletedProcess([], 0, "rendered", "digest: sha256:wrong")
        with patch.object(CONTRACT.subprocess, "run", return_value=rendered) as run:
            with self.assertRaisesRegex(ValueError, "OCI digest changed"):
                CONTRACT.render_pinned_chart(self.COMMAND)
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
