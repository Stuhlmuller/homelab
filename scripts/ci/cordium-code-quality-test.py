#!/usr/bin/env python3
"""Verify fixed runner-only writes, existing settings preservation and async receipts."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location("quality", Path(__file__).resolve().parents[1] / "cordium-code-quality.py")
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)
CURRENT = {"state": "configured", "runner_type": "standard", "runner_label": "",
           "languages": ["go", "javascript-typescript", "python"], "ai_findings_option": "disabled"}


class Reconcile(unittest.TestCase):
    def test_preview_convergence_and_disabled_setup_never_write(self):
        for current, verified in ((CURRENT, False), ({**CURRENT, **quality.DESIRED}, True)):
            api = Mock(return_value=copy.deepcopy(current))
            self.assertEqual(quality.reconcile(api)["verified"], verified)
            api.assert_called_once_with("GET", quality.ENDPOINT)
        api = Mock(return_value={**CURRENT, "state": "not-configured"})
        with self.assertRaises(RuntimeError):
            quality.reconcile(api, True)
        api.assert_called_once_with("GET", quality.ENDPOINT)
        api = Mock(return_value=copy.deepcopy(CURRENT))
        with self.assertRaises(RuntimeError):
            quality.reconcile(api, True, before_write=Mock(side_effect=RuntimeError("main changed")))
        api.assert_called_once_with("GET", quality.ENDPOINT)
        api = Mock(return_value={**CURRENT, **quality.DESIRED})
        self.assertEqual(quality.reconcile(api, True), {"verified": True, "changed": False})
        api.assert_called_once_with("GET", quality.ENDPOINT)

    def test_write_has_only_runner_fields_and_preserves_existing_settings(self):
        events = []
        responses = [copy.deepcopy(CURRENT), {"run_id": 123}, {**CURRENT, **quality.DESIRED}]
        def api(*args):
            events.append(args)
            return responses.pop(0)
        result = quality.reconcile(api, True, before_write=lambda: events.append("reviewed-main"))
        self.assertEqual(events, [("GET", quality.ENDPOINT), "reviewed-main",
                                  ("PATCH", quality.ENDPOINT, quality.DESIRED), ("GET", quality.ENDPOINT)])
        self.assertEqual(result, {"verified": True, "changed": True, "validation_run_id": 123})

    def test_async_is_pending_and_preservation_failure_cannot_report_success(self):
        api = Mock(side_effect=[copy.deepcopy(CURRENT), {"run_id": 123}, copy.deepcopy(CURRENT)])
        self.assertEqual(quality.reconcile(api, True), {"verified": False, "changed": True, "validation_run_id": 123})
        for changes in ({"state": "not-configured"}, {"languages": ["ruby"]}, {"ai_findings_option": "on_push"}):
            api = Mock(side_effect=[copy.deepcopy(CURRENT), {"run_id": 123}, {**CURRENT, **quality.DESIRED, **changes}])
            with self.assertRaises(RuntimeError):
                quality.reconcile(api, True)


if __name__ == "__main__":
    unittest.main()
