import copy
import base64
import hashlib
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import unittest
import tempfile

spec = importlib.util.spec_from_file_location("scan", Path(__file__).with_name("litellm-scan-check.py"))
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)
CONFIG = json.dumps({"os": "linux", "architecture": "amd64"}).encode()
IMAGE = "sha256:" + hashlib.sha256(CONFIG).hexdigest()


class ScanGate(unittest.TestCase):
    def report(self):
        now = datetime.now(timezone.utc).isoformat()
        return {"source": {"type": "image", "target": {"imageID": IMAGE, "os": "linux",
                "architecture": "amd64", "layers": ["fixture"], "imageSize": 1,
                "config": base64.b64encode(CONFIG).decode()}},
                "distro": {"name": "wolfi"}, "matches": [], "descriptor": {
                    "name": "grype", "version": "0.112.0", "timestamp": now,
                    "db": {"status": {"valid": True, "built": now}}, "configuration": {
                        "only-fixed": False, "only-notfixed": False, "ignore-wontfix": "",
                        "ignore": [], "exclude": [], "vex-documents": [], "search": {"scope": "squashed"}}}}

    def test_complete_and_unfixed(self):
        report = self.report()
        scan.verify(report, IMAGE)
        report["matches"] = [{"vulnerability": {"fix": {"state": "not-fixed"}}}]
        scan.verify(report, IMAGE)
        self.assertEqual(len(report["matches"]), 1)

    def test_docker_archive_identity(self):
        report = self.report()
        report["source"]["target"].update(os="", architecture="")
        scan.verify(report, IMAGE)
        report["source"]["target"]["config"] = base64.b64encode(json.dumps({"os": "linux", "architecture": "arm64"}).encode()).decode()
        with self.assertRaisesRegex(AssertionError, "identity"):
            scan.verify(report, IMAGE)
        wrong_config = json.dumps({"os": "linux", "architecture": "arm64"}).encode()
        wrong_image = "sha256:" + hashlib.sha256(wrong_config).hexdigest()
        report["source"]["target"]["imageID"] = wrong_image
        with self.assertRaisesRegex(AssertionError, "identity"):
            scan.verify(report, wrong_image)

    def test_unspecified_fix_state_remains_unresolved(self):
        report = self.report()
        report["matches"] = [{"vulnerability": {"fix": {"state": "", "versions": []}}}]
        before = copy.deepcopy(report)
        scan.verify(report, IMAGE)
        self.assertEqual(report, before, "Do not remove or rewrite unresolved findings")
        report["matches"][0]["vulnerability"]["fix"]["versions"] = ["fixture-fixed-version"]
        with self.assertRaisesRegex(AssertionError, "remediation"):
            scan.verify(report, IMAGE)
        report["matches"][0]["vulnerability"]["fix"]["versions"] = []
        report["matches"][0]["vulnerability"]["fix"]["available"] = [{"version": "fixture-fix"}]
        with self.assertRaisesRegex(AssertionError, "remediation"):
            scan.verify(report, IMAGE)

    def test_refusals(self):
        base = self.report()
        mutations = [
            lambda r: r["source"]["target"].update(imageID="sha256:" + "1" * 64),
            lambda r: r["descriptor"]["db"]["status"].update(valid=False),
            lambda r: r["descriptor"].update(timestamp=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()),
            lambda r: r["descriptor"]["db"]["status"].update(built=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat()),
            lambda r: r["descriptor"]["configuration"].update(ignore=[{"fixture": "suppression"}]),
            lambda r: r["descriptor"]["configuration"].update(**{"only-fixed": True}),
            lambda r: r.update(ignoredMatches=[{}]),
            lambda r: r.update(matches=[{"vulnerability": {"fix": {"state": "fixed"}}}]),
            lambda r: r.update(matches=[{"vulnerability": {"fix": {"state": "unexpected"}}}]),
            lambda r: r.update(matches=None),
        ]
        for mutate in mutations:
            report = copy.deepcopy(base)
            mutate(report)
            with self.subTest(mutate=mutate), self.assertRaises((AssertionError, KeyError, TypeError, ValueError)):
                scan.verify(report, IMAGE)

    def test_cli_never_exposes_report_values(self):
        report = self.report()
        marker = "PRIVATE_REPORT_VALUE_MUST_NOT_ESCAPE"
        report["source"]["target"]["os"] = marker
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(report))
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                self.assertEqual(scan.main([str(path), IMAGE]), 1)
            self.assertEqual(output.getvalue(), "Private report validation failed: identity; findings withheld.\n")
            self.assertNotIn(marker, output.getvalue())
            path.write_text('{"' + marker + '":')
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                self.assertEqual(scan.main([str(path), IMAGE]), 1)
            self.assertEqual(output.getvalue(), "Private report validation failed: schema; findings withheld.\n")


if __name__ == "__main__":
    unittest.main()
