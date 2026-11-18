#!/usr/bin/env python3
"""The public chart fetch can retry without loosening its digest gate."""

import importlib.util
import subprocess
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
        success = subprocess.CompletedProcess([], 0, "rendered", CONTRACT.CHART_DIGEST)
        with patch.object(CONTRACT.subprocess, "run", side_effect=[*failures, success]) as run, \
                patch.object(CONTRACT.time, "sleep") as sleep:
            result = CONTRACT.render_pinned_chart(["helm", "template"])
        self.assertIs(result, success)
        self.assertEqual(run.call_count, 3)
        self.assertEqual([call.args for call in sleep.call_args_list], [(2,), (4,)])

    def test_exhausted_fetch_fails_without_private_output(self):
        failure = subprocess.CompletedProcess([], 1, "", "403 PRIVATE_URL_TOKEN")
        with patch.object(CONTRACT.subprocess, "run", return_value=failure) as run, \
                patch.object(CONTRACT.time, "sleep") as sleep:
            with self.assertRaisesRegex(ValueError, r"after 4 attempts \(access\)") as raised:
                CONTRACT.render_pinned_chart(["helm", "template"])
        self.assertNotIn("PRIVATE_URL_TOKEN", str(raised.exception))
        self.assertEqual(run.call_count, 4)
        self.assertEqual([call.args for call in sleep.call_args_list], [(2,), (4,), (8,)])

    def test_successful_render_still_requires_pinned_digest(self):
        rendered = subprocess.CompletedProcess([], 0, "rendered", "digest: sha256:wrong")
        with patch.object(CONTRACT, "render_pinned_chart", return_value=rendered), \
                patch.object(CONTRACT, "load_yaml", return_value={"servers": [{"servicePort": 53},
                                                                        {"servicePort": 53}]}):
            with self.assertRaisesRegex(ValueError, "OCI digest changed"):
                CONTRACT.rendered_contract()


if __name__ == "__main__":
    unittest.main()
