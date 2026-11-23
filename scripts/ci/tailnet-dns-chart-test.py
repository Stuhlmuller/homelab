#!/usr/bin/env python3
"""The DNS chart check rejects unreviewed bytes before invoking Helm."""

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


class ChartContractTest(unittest.TestCase):
    def test_wrong_package_hash_blocks_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrong = Path(tmp) / "k8s-gateway-4.0.0.tgz"
            wrong.write_bytes(b"wrong package")
            with patch.object(CONTRACT, "CHART_PACKAGE", wrong), \
                    patch.object(CONTRACT.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "package is missing or changed"):
                    CONTRACT.render_pinned_chart()
            run.assert_not_called()

    def test_catalog_hash_change_blocks_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "catalog.json"
            catalog.write_text(json.dumps({"charts": [{"chart": "k8s-gateway", "version": "4.0.0",
                                                     "repository": "codeberg.org/k8s-gateway/charts",
                                                     "sha256": "0" * 64}]}))
            with patch.object(CONTRACT, "CHART_CATALOG", catalog), \
                    patch.object(CONTRACT.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "catalog hash changed"):
                    CONTRACT.render_pinned_chart()
            run.assert_not_called()

    def test_template_error_withholds_raw_output(self):
        failure = subprocess.CompletedProcess([], 1, "", "template: invalid setting 403 timeout")
        with patch.object(CONTRACT.subprocess, "run", return_value=failure) as run:
            with self.assertRaisesRegex(ValueError, "pinned chart template failed") as raised:
                CONTRACT.render_pinned_chart()
        self.assertNotIn("403 timeout", str(raised.exception))
        self.assertEqual(run.call_count, 1)

    def test_verified_package_renders_once(self):
        success = subprocess.CompletedProcess([], 0, "rendered", "")
        with patch.object(CONTRACT.subprocess, "run", return_value=success) as run:
            self.assertEqual(CONTRACT.render_pinned_chart(), "rendered")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][:4],
                         ["helm", "template", "tailnet-dns", str(CONTRACT.CHART_PACKAGE)])
        self.assertEqual(run.call_args.kwargs["timeout"], 20)


if __name__ == "__main__":
    unittest.main()
