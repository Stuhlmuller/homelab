import copy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("scan", Path(__file__).with_name("litellm-scan-check.py"))
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)
IMAGE = "sha256:" + "0" * 64


class ScanGate(unittest.TestCase):
    def report(self):
        now = datetime.now(timezone.utc).isoformat()
        return {"source": {"type": "image", "target": {"imageID": IMAGE, "os": "linux",
                "architecture": "amd64", "layers": ["fixture"], "imageSize": 1}},
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


if __name__ == "__main__":
    unittest.main()
