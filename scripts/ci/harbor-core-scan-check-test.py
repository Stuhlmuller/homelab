"""Exact-image, freshness, completeness and remediation audit boundaries."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from contextlib import redirect_stdout
import io
import tempfile

spec = importlib.util.spec_from_file_location("scan", Path(__file__).with_name("harbor-core-scan-check.py"))
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)
CONFIG = json.dumps({"os": "linux", "architecture": "amd64"}).encode()
IMAGE = "sha256:" + hashlib.sha256(CONFIG).hexdigest()


class ScanTests(unittest.TestCase):
    def report(self):
        now = datetime.now(timezone.utc).isoformat()
        return {"source": {"type": "image", "target": {"imageID": IMAGE, "os": "", "architecture": "",
            "layers": ["fixture"], "imageSize": 1, "config": base64.b64encode(CONFIG).decode()}},
            "distro": {"name": "photon", "version": "5.0"}, "matches": [], "descriptor": {
            "name": "grype", "version": "0.112.0", "timestamp": now,
            "db": {"status": {"valid": True, "built": now}}, "configuration": {
            "only-fixed": False, "only-notfixed": False, "ignore-wontfix": "", "ignore": [],
            "exclude": [], "vex-documents": [], "search": {"scope": "squashed"}}}}

    def test_unresolved_findings_remain_unchanged(self):
        for state in ("not-fixed", "unknown", "wont-fix", ""):
            report = self.report()
            report["matches"] = [{"vulnerability": {"severity": "Unknown", "fix": {"state": state, "versions": []}}}]
            original = copy.deepcopy(report)
            scan.verify(report, IMAGE)
            self.assertEqual(report, original)

    def test_refuses_available_fixes(self):
        for fix in ({"state": "fixed", "versions": ["fixed-version"]},
                    {"state": "", "versions": ["fixed-version"]},
                    {"state": "unknown", "versions": [], "available": [{"version": "fixed-version"}]}):
            report = self.report()
            report["matches"] = [{"vulnerability": {"severity": "Unknown", "fix": fix}}]
            with self.assertRaisesRegex(AssertionError, "remediation"):
                scan.verify(report, IMAGE)

    def test_refuses_wrong_or_filtered_or_stale_reports(self):
        changes = [
            lambda r: r["source"].update(type="directory"),
            lambda r: r["source"]["target"].update(imageID="sha256:" + "1" * 64),
            lambda r: r["source"]["target"].update(config=base64.b64encode(b"{}").decode()),
            lambda r: r["source"]["target"].update(layers=[]),
            lambda r: r["source"]["target"].update(architecture="arm64"),
            lambda r: r["distro"].update(name="unknown"),
            lambda r: r["descriptor"].update(version="other"),
            lambda r: r["descriptor"]["db"]["status"].update(valid=False),
            lambda r: r["descriptor"]["db"]["status"].update(built=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat()),
            lambda r: r["descriptor"]["configuration"].update(**{"only-fixed": True}),
            lambda r: r["descriptor"]["configuration"].update(exclude=["fixture"]),
            lambda r: r.update(ignoredMatches=["fixture"]),
        ]
        scan.verify(self.report(), IMAGE)
        for change in changes:
            report = self.report()
            change(report)
            with self.assertRaises(AssertionError):
                scan.verify(report, IMAGE)

    def test_summary_withholds_raw_image_metadata_and_clearance(self):
        report = self.report()
        raw = json.dumps({"os": "linux", "architecture": "amd64", "env": ["PRIVATE_VALUE=fixture-do-not-print"]}).encode()
        image = "sha256:" + hashlib.sha256(raw).hexdigest()
        report["source"]["target"].update(imageID=image, config=base64.b64encode(raw).decode())
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "report.json"
            path.write_text(json.dumps(report))
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(scan.main([str(path), image]), 0)
        text = output.getvalue()
        self.assertNotIn("fixture-do-not-print", text)
        self.assertIn('"cve_clearance": false', text)
        self.assertIn(image, text)


if __name__ == "__main__":
    unittest.main()
