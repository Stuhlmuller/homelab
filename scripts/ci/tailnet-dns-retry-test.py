#!/usr/bin/env python3
"""The public chart fetch can retry without loosening its package checks."""

import contextlib
import importlib.util
import io
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
    def test_recovers_after_transient_registry_failure(self):
        failures = [subprocess.CompletedProcess([], 1, "", "429 PRIVATE_URL") for _ in range(2)]
        success = subprocess.CompletedProcess([], 0, "", CONTRACT.CHART_DIGEST)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(CONTRACT.subprocess, "run", side_effect=[*failures, success]) as run, \
                patch.object(CONTRACT.time, "sleep") as sleep:
            self.assertEqual(CONTRACT.fetch_pinned_chart(Path(tmp)),
                             Path(tmp) / "k8s-gateway-4.0.0.tgz")
        self.assertEqual(run.call_count, 3)
        self.assertEqual([call.args for call in sleep.call_args_list], [(2,), (4,)])
        self.assertTrue(all(call.kwargs["timeout"] == 20 for call in run.call_args_list))
        self.assertEqual(run.call_args.args[0][:3], ["helm", "pull", CONTRACT.CHART])

    def test_exhausted_fetch_uses_reviewed_package_without_private_output(self):
        failure = subprocess.CompletedProcess([], 1, "", "403 PRIVATE_URL_TOKEN")
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(output), \
                patch.object(CONTRACT.subprocess, "run", return_value=failure) as run, \
                patch.object(CONTRACT.time, "sleep") as sleep:
            self.assertEqual(CONTRACT.fetch_pinned_chart(Path(tmp)), CONTRACT.CHART_PACKAGE)
        self.assertEqual(run.call_count, 4)
        self.assertEqual([call.args for call in sleep.call_args_list], [(2,), (4,), (8,)])
        self.assertIn("(access)", output.getvalue())
        self.assertNotIn("PRIVATE_URL_TOKEN", output.getvalue())

    def test_fetch_timeouts_are_bounded_before_fallback(self):
        timeout = subprocess.TimeoutExpired(["helm", "pull"], 20, stderr=b"PRIVATE_TOKEN")
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()), \
                patch.object(CONTRACT.subprocess, "run", side_effect=timeout) as run, \
                patch.object(CONTRACT.time, "sleep"):
            self.assertEqual(CONTRACT.fetch_pinned_chart(Path(tmp)), CONTRACT.CHART_PACKAGE)
        self.assertEqual(run.call_count, 4)
        self.assertTrue(all(call.kwargs["timeout"] == 20 for call in run.call_args_list))

    def test_successful_pull_still_requires_pinned_oci_digest(self):
        wrong = subprocess.CompletedProcess([], 0, "", "digest: sha256:wrong")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(CONTRACT.subprocess, "run", return_value=wrong) as run:
            with self.assertRaisesRegex(ValueError, "OCI digest changed"):
                CONTRACT.fetch_pinned_chart(Path(tmp))
        self.assertEqual(run.call_count, 1)

    def test_wrong_package_hash_blocks_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrong = Path(tmp) / "k8s-gateway-4.0.0.tgz"
            wrong.write_bytes(b"wrong package")
            with patch.object(CONTRACT, "fetch_pinned_chart", return_value=wrong), \
                    patch.object(CONTRACT.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "package is missing or changed"):
                    CONTRACT.render_pinned_chart()
            run.assert_not_called()

    def test_catalog_hash_change_blocks_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "catalog.json"
            catalog.write_text(json.dumps({"charts": [{"chart": "k8s-gateway", "version": "4.0.0",
                                                     "repository": "codeberg.org/k8s-gateway/charts",
                                                     "sha256": "0" * 64}]}))
            with patch.object(CONTRACT, "CHART_CATALOG", catalog), \
                    patch.object(CONTRACT, "fetch_pinned_chart") as fetch:
                with self.assertRaisesRegex(ValueError, "catalog hash changed"):
                    CONTRACT.render_pinned_chart()
            fetch.assert_not_called()

    def test_template_error_with_fetch_like_token_fails_without_fallback(self):
        failure = subprocess.CompletedProcess([], 1, "", "template: invalid setting 403 timeout")
        with patch.object(CONTRACT, "fetch_pinned_chart", return_value=CONTRACT.CHART_PACKAGE), \
                patch.object(CONTRACT.subprocess, "run", return_value=failure) as run:
            with self.assertRaisesRegex(ValueError, "pinned chart template failed") as raised:
                CONTRACT.render_pinned_chart()
        self.assertNotIn("403 timeout", str(raised.exception))
        self.assertEqual(run.call_count, 1)

    def test_verified_package_renders_once(self):
        success = subprocess.CompletedProcess([], 0, "rendered", "")
        with patch.object(CONTRACT, "fetch_pinned_chart", return_value=CONTRACT.CHART_PACKAGE), \
                patch.object(CONTRACT.subprocess, "run", return_value=success) as run:
            self.assertEqual(CONTRACT.render_pinned_chart(), "rendered")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][3], str(CONTRACT.CHART_PACKAGE))
        self.assertEqual(run.call_args.kwargs["timeout"], 20)


if __name__ == "__main__":
    unittest.main()
