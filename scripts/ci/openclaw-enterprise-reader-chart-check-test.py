#!/usr/bin/env python3
"""Exercise the pinned chart checkout and protected reader policy gate."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "scripts/ci/openclaw-enterprise-reader-chart-check.py"
SPEC = importlib.util.spec_from_file_location("reader_chart_check", CHECK)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def command(*args):
    return subprocess.run(["git", *map(str, args)], check=True,
                          capture_output=True, text=True).stdout.strip()


class ReaderChartGate(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="oce-reader-gate-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repository = self.root / "upstream"
        self.repository.mkdir()
        command("init", "--quiet", self.repository)
        command("-C", self.repository, "config", "user.name", "Fixture")
        command("-C", self.repository, "config", "user.email", "fixture@example.invalid")
        self.contract = self.root / "source.json"
        self.marker = self.root / "reader-ran"
        self.reader = self.root / "reader-test.py"
        self.reader.write_text(
            "from pathlib import Path\n"
            "import subprocess\n"
            "import sys\n"
            "assert sys.argv[1] == '--upstream-root'\n"
            "checkout = Path(sys.argv[2])\n"
            "assert (checkout / 'deploy/helm/openclaw-enterprise/Chart.yaml').is_file()\n"
            "revision = subprocess.check_output(['git', '-C', str(checkout), "
            "'rev-parse', 'HEAD'], text=True).strip()\n"
            f"Path({str(self.marker)!r}).write_text(revision)\n")

    def commit(self, chart=True):
        if chart:
            directory = self.repository / "deploy/helm/openclaw-enterprise"
            directory.mkdir(parents=True)
            (directory / "Chart.yaml").write_text("apiVersion: v2\nname: oce\nversion: 0.1.0\n")
        else:
            (self.repository / "README.md").write_text("No chart\n")
        command("-C", self.repository, "add", ".")
        command("-C", self.repository, "commit", "--quiet", "-m", "fixture")
        revision = command("-C", self.repository, "rev-parse", "HEAD")
        self.contract.write_text(json.dumps({"revision": revision}))
        return revision

    def test_exact_local_pin_runs_reader_test_on_clean_chart(self):
        revision = self.commit()
        MODULE.check(self.contract, self.repository, self.reader)
        self.assertEqual(self.marker.read_text(), revision)

    def test_unknown_pin_stops_before_reader_test(self):
        self.commit()
        self.contract.write_text(json.dumps({"revision": "0" * 40}))
        with self.assertRaises(subprocess.CalledProcessError):
            MODULE.check(self.contract, self.repository, self.reader)
        self.assertFalse(self.marker.exists())

    def test_missing_chart_stops_before_reader_test(self):
        self.commit(chart=False)
        with self.assertRaisesRegex(FileNotFoundError, "Pinned Enterprise chart"):
            MODULE.check(self.contract, self.repository, self.reader)
        self.assertFalse(self.marker.exists())

    def test_wrong_head_and_dirty_checkout_stop_before_reader_test(self):
        revision = self.commit()
        original = MODULE.git
        for affected, value, error in (("rev-parse", "f" * 40, "HEAD differs"),
                                       ("status", "?? untracked", "checkout is dirty")):
            with self.subTest(affected=affected):
                def altered(*args):
                    if affected in args:
                        return value
                    return original(*args)

                with mock.patch.object(MODULE, "git", side_effect=altered):
                    with self.assertRaisesRegex(ValueError, error):
                        MODULE.check(self.contract, self.repository, self.reader)
                self.assertFalse(self.marker.exists())
        self.assertEqual(MODULE.pinned_revision(self.contract), revision)

    def test_malformed_pin_stops_before_git_fetch(self):
        self.contract.write_text(json.dumps({"revision": "main"}))
        with mock.patch.object(MODULE, "git") as git:
            with self.assertRaisesRegex(ValueError, "full SHA"):
                MODULE.check(self.contract, self.repository, self.reader)
            git.assert_not_called()

    def test_validate_always_runs_pinned_chart_check_without_credentials_or_skip(self):
        workflow = json.loads(subprocess.run(
            ["yq", "-o=json", "-I=0", ".", str(ROOT / ".github/workflows/validate.yml")],
            check=True, capture_output=True, text=True).stdout)
        self.assertIn("pull_request", workflow["on"])
        self.assertEqual(workflow["on"]["push"]["branches"], ["main"])
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        job = workflow["jobs"]["repo"]
        self.assertNotIn("if", job)
        steps = job["steps"]
        self.assertEqual([step["name"] for step in steps[:4]], [
            "Checkout", "Install Nix", "Check Reader Chart Gate Contract",
            "Check Pinned Reader Policy Overlap"])
        self.assertEqual(steps[0]["uses"],
                         "chainguard-actions/actions-checkout@9b08549f11b1cea64a914e482f95fa1413656505")
        self.assertEqual(steps[0]["with"], {"fetch-depth": 0, "persist-credentials": False})
        self.assertEqual(steps[1]["uses"],
                         "chainguard-actions/cachix-install-nix-action@043d5ae37e81d3c6b1604becbdc6aefbdc9fa909")
        self.assertEqual(steps[2]["run"],
                         "nix develop --command python3 -I scripts/ci/openclaw-enterprise-reader-chart-check-test.py")
        self.assertEqual(steps[3]["run"],
                         "nix develop --command python3 -I scripts/ci/openclaw-enterprise-reader-chart-check.py")
        for step in steps[:4]:
            self.assertNotIn("if", step)
            self.assertNotIn("continue-on-error", step)
            self.assertNotIn("env", step)
        self.assertLess(3, [step["name"] for step in steps].index("Secret scan"))
        self.assertEqual(MODULE.UPSTREAM_URL,
                         "https://github.com/openclaw/openclaw-enterprise.git")


if __name__ == "__main__":
    unittest.main()
