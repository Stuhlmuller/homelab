#!/usr/bin/env python3
"""Test exact review boundaries, optionally against the pinned native scanner."""
import base64
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    "review", Path(__file__).with_name("checkov-reviewed-findings.py"))
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
HCL_COMPATIBILITY_PATHS = {
    "IaC/root.hcl",
    "IaC/terragrunt-catalog/units/operator/entra-emergency-global-admin/terragrunt.hcl",
}
NATIVE = "--native" in sys.argv
if NATIVE:
    sys.argv.remove("--native")


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.path = "fixture.json"
        (self.root / self.path).write_text("{}\n")
        self.hash = hashlib.sha1(b"inert reviewed fixture").hexdigest()
        self.entry = {"path": self.path, "check_id": "CKV_SECRET_6", "fingerprint": self.hash,
                      "max_occurrences": 1, "reason": "Synthetic unit-test value"}
        self.allow = {"version": 1, "checkov_versions": list(review.VERSIONS), "findings": [self.entry]}
        self.finding = {"check_id": "CKV_SECRET_6", "resource": self.hash,
                        "check_result": {"result": "FAILED"}, "file_path": "/" + self.path,
                        "file_abs_path": str(self.root / self.path), "file_line_range": [1, 2],
                        "code_block": [[1, "PRIVATE-SCANNER-CONTENT"]]}
        self.report = {"check_type": "secrets", "results": {"failed_checks": [self.finding]},
                       "summary": {"checkov_version": review.VERSIONS[0], "passed": 0, "failed": 1,
                                   "skipped": 0, "parsing_errors": 0, "resource_count": 1}}

    def assess(self, report=None, code=1, selected=None, mode="secrets"):
        return review.assess(json.dumps(self.report if report is None else report), code, mode,
                             self.root, selected or {self.path}, review.load_reviews(json.dumps(self.allow)))

    def test_exact_match_and_zero_findings(self):
        self.assertEqual(self.assess(), (1, []))
        empty = copy.deepcopy(self.report)
        empty["results"]["failed_checks"] = []
        empty["summary"].update(failed=0, resource_count=0)
        self.assertEqual(self.assess(empty, code=0), (0, []))
        self.assertEqual(self.assess(empty["summary"], code=0), (0, []))
        self.assertEqual(self.assess([dict(empty, check_type="terraform")], code=0, mode="diff"), (0, []))
        with self.assertRaises(review.ReviewError):
            self.assess(empty["summary"], code=1)
        empty["summary"]["passed"] = False
        with self.assertRaises(review.ReviewError):
            self.assess(empty["summary"], code=0)

    def test_changed_value_new_check_and_same_value_new_path_fail(self):
        for key, value in [("resource", "0" * 40), ("check_id", "CKV_SECRET_999")]:
            with self.subTest(key=key):
                changed = copy.deepcopy(self.report)
                changed["results"]["failed_checks"][0][key] = value
                self.assertEqual(len(self.assess(changed)[1]), 1)
        changed = copy.deepcopy(self.report)
        changed["results"]["failed_checks"][0].update(
            file_path="/other.json", file_abs_path=str(self.root / "other.json"))
        self.assertEqual(len(self.assess(changed, selected={"other.json"})[1]), 1)

    def test_new_secret_same_file_and_nonsecret_failure_preserved(self):
        changed = copy.deepcopy(self.report)
        extra = copy.deepcopy(self.finding)
        extra["resource"] = "0" * 40
        changed["results"]["failed_checks"].append(extra)
        changed["summary"]["failed"] = 2
        self.assertEqual(self.assess(changed)[0], 1)
        self.assertEqual(len(self.assess(changed)[1]), 1)
        docker = copy.deepcopy(self.report)
        docker["check_type"] = "dockerfile"
        docker["results"]["failed_checks"][0]["check_id"] = "CKV_DOCKER_2"
        self.assertEqual(len(self.assess([self.report, docker], mode="diff")[1]), 1)

    def test_occurrence_limit(self):
        self.report["results"]["failed_checks"] *= 2
        self.report["summary"]["failed"] = 2
        with self.assertRaises(review.ReviewError):
            self.assess()
        self.entry["max_occurrences"] = 2
        self.assertEqual(self.assess(), (2, []))

    def test_output_errors_fail_closed(self):
        mutations = [
            lambda d: d["summary"].update(parsing_errors=1),
            lambda d: d["summary"].update(failed=0),
            lambda d: d["summary"].update(passed=True),
            lambda d: d["summary"].update(checkov_version="unreviewed"),
            lambda d: d.update(check_type="terraform"),
            lambda d: d.pop("results"),
            lambda d: d["results"]["failed_checks"][0].update(file_path="/../fixture.json"),
            lambda d: d["results"]["failed_checks"][0].update(file_abs_path="/outside.json"),
            lambda d: d["results"]["failed_checks"][0].update(file_line_range=[0, 1]),
            lambda d: d["results"]["failed_checks"][0].update(check_result={"result": "PASSED"}),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(self.report)
                mutation(changed)
                with self.assertRaises(review.ReviewError):
                    self.assess(changed)
        for value in [[], {}, [self.report, self.report]]:
            with self.assertRaises(review.ReviewError):
                self.assess(value)
        for code in [0, 2, -9]:
            with self.assertRaises(review.ReviewError):
                self.assess(code=code)
        for raw in ["", "not JSON", '{"summary":{},"summary":{}}']:
            with self.assertRaises(review.ReviewError):
                review.assess(raw, 1, "secrets", self.root, {self.path}, {})

    def test_selection_and_review_schema(self):
        for path in ["../fixture.json", "a/../fixture.json", "/fixture.json", "./fixture.json",
                     "a//fixture.json", "a\\fixture.json", "missing.json", "--soft-fail"]:
            with self.subTest(path=path), self.assertRaises(review.ReviewError):
                review.selected_files(self.root, [path])
        with self.assertRaises(review.ReviewError):
            review.selected_files(self.root, [])
        (self.root / "link.json").symlink_to(self.root / self.path)
        with self.assertRaises(review.ReviewError):
            review.selected_files(self.root, ["link.json"])
        for key, value in [("check_id", "CKV_DOCKER_2"), ("fingerprint", "invalid"),
                           ("max_occurrences", True), ("max_occurrences", 0),
                           ("path", "../fixture.json"), ("reason", "")]:
            invalid = copy.deepcopy(self.allow)
            invalid["findings"][0][key] = value
            with self.assertRaises(review.ReviewError):
                review.load_reviews(json.dumps(invalid))
        self.allow["findings"] *= 2
        with self.assertRaises(review.ReviewError):
            review.load_reviews(json.dumps(self.allow))

    def test_unreadable_oversize_and_binary_input_fail_closed(self):
        target = self.root / self.path
        target.chmod(0)
        try:
            with self.assertRaises(review.ReviewError):
                review.selected_files(self.root, [self.path])
        finally:
            target.chmod(0o600)
        target.write_bytes(b"\xff")
        with self.assertRaises(review.ReviewError):
            review.selected_files(self.root, [self.path])
        with target.open("wb") as output:
            output.truncate(review.MAX_FILE_SIZE + 1)
        with self.assertRaises(review.ReviewError):
            review.selected_files(self.root, [self.path])

    def test_cli_never_prints_scanner_values(self):
        config = self.root / "review.json"
        config.write_text(json.dumps(self.allow))
        self.finding["resource"] = "0" * 40
        output = io.StringIO()
        result = subprocess.CompletedProcess([], 1, json.dumps(self.report), "")
        with mock.patch.object(review, "ROOT", self.root), mock.patch.object(review, "REVIEWS", config), \
                mock.patch.object(review.subprocess, "run", return_value=result) as run, \
                mock.patch.dict(os.environ, {"CHECKOV_MAX_FILE_SIZE": "1"}), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertTrue(review.main(["secrets", "-f", self.path]))
        self.assertNotIn("PRIVATE", output.getvalue())
        self.assertNotIn("CHECKOV_MAX_FILE_SIZE", run.call_args.kwargs["env"])
        self.assertEqual(run.call_args.args[0], ["checkov", "--enable-secret-scan-all-files", "--output",
                                               "json", "--framework", "secrets", "-f", self.path])

    def test_scanner_diagnostics_and_unreviewed_version_fail_closed(self):
        config = self.root / "review.json"
        config.write_text(json.dumps(self.allow))
        result = subprocess.CompletedProcess([], 1, json.dumps(self.report), "PRIVATE-ERROR")
        output = io.StringIO()
        with mock.patch.object(review, "ROOT", self.root), mock.patch.object(review, "REVIEWS", config), \
                mock.patch.object(review.subprocess, "run", return_value=result), \
                contextlib.redirect_stderr(output), self.assertRaises(review.ReviewError):
            review.main(["secrets", "-f", self.path])
        self.assertNotIn("PRIVATE-ERROR", output.getvalue())
        for version in review.VERSIONS:
            self.report["summary"]["checkov_version"] = version
            self.assertEqual(self.assess(), (1, []))
        self.allow["checkov_versions"].append("unreviewed")
        with self.assertRaises(review.ReviewError):
            review.load_reviews(json.dumps(self.allow))

    def test_hcl_compatibility_hook_selection(self):
        config = json.loads(subprocess.check_output(
            ["yq", "-o=json", ".", str(review.ROOT / ".pre-commit-config.yaml")], text=True))
        hooks = {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}
        diff, secrets = hooks["checkov_diff"], hooks["checkov_secrets"]
        tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=review.ROOT).decode().split("\0")
        excluded_hcl = {path for path in tracked if path.endswith(".hcl") and re.search(diff["exclude"], path)}
        self.assertEqual(excluded_hcl, HCL_COMPATIBILITY_PATHS)
        for path in HCL_COMPATIBILITY_PATHS:
            for scope in (config, secrets, hooks["terragrunt-hcl-fmt"]):
                self.assertIsNotNone(re.search(scope.get("files", ""), path))
                self.assertNotRegex(path, scope.get("exclude", "^$"))
                self.assertFalse(scope.get("exclude_types"))
                self.assertEqual(scope.get("types", ["file"]), ["file"])
            for adjacent in (path + ".backup", "copy/" + path, path.replace(".hcl", "-other.hcl")):
                self.assertNotRegex(adjacent, diff["exclude"])
        self.assertRegex("clusters/example/config.yaml", diff["exclude"])
        self.assertRegex("clusters/example/config.yml", diff["exclude"])
        self.assertNotRegex("IaC/example.tf", diff["exclude"])

    @unittest.skipUnless(NATIVE, "Run --native with reviewed Checkov and Terragrunt on PATH")
    def test_native_hcl_secret_and_syntax_boundaries(self):
        value = base64.b64encode(bytes(range(32, 96))).decode()
        for path in HCL_COMPATIBILITY_PATHS:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('locals {\n  fixture_secret = "' + value + '"\n}\n')
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        result = subprocess.run(
            ["checkov", "--framework", "secrets", "--enable-secret-scan-all-files", "--output", "json",
             "-f", *sorted(HCL_COMPATIBILITY_PATHS)], cwd=self.root, capture_output=True, text=True,
            env=environment, timeout=120, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(result.stderr.strip())
        reviewed, remaining = self.assess(review.decode(result.stdout), selected=HCL_COMPATIBILITY_PATHS)
        self.assertEqual(reviewed, 0)
        self.assertEqual({path for _, path, _ in remaining}, HCL_COMPATIBILITY_PATHS)
        self.assertEqual(len(remaining), 2)
        for path in HCL_COMPATIBILITY_PATHS:
            with self.subTest(path=path):
                result = subprocess.run(["terragrunt", "hcl", "fmt", "--file", path], cwd=self.root,
                                        capture_output=True, text=True, timeout=30, check=False)
                self.assertEqual(result.returncode, 0)
                (self.root / path).write_text("locals { broken = [ }\n")
                result = subprocess.run(["terragrunt", "hcl", "fmt", "--check", "--file", path],
                                        cwd=self.root, capture_output=True, text=True, timeout=30, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid expression", result.stderr)

    @unittest.skipUnless(NATIVE, "Run --native with either reviewed pinned Checkov on PATH")
    def test_native_pinned_scanner(self):
        # Generated inert bytes are intentionally high entropy; never a real credential.
        value = base64.b64encode(bytes(range(32, 96))).decode()
        (self.root / self.path).write_text(json.dumps({"secret": value}) + "\n")
        command = ["checkov", "--framework", "secrets", "--enable-secret-scan-all-files",
                   "--output", "json", "-f", self.path]
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True,
                                env=environment, timeout=120, check=False)
        report = review.decode(result.stdout)
        findings = report["results"]["failed_checks"]
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check_id"], "CKV_SECRET_6")
        self.entry["fingerprint"] = findings[0]["resource"]
        self.assertEqual(self.assess(report), (1, []))
        (self.root / "other.json").write_text((self.root / self.path).read_text())
        result = subprocess.run(command[:-1] + ["other.json"], cwd=self.root, capture_output=True,
                                text=True, env=environment, timeout=120, check=False)
        self.assertEqual(len(self.assess(review.decode(result.stdout), selected={"other.json"})[1]), 1)
        (self.root / self.path).write_text("{}\n")
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True,
                                env=environment, timeout=120, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.assess(review.decode(result.stdout), code=0), (0, []))


if __name__ == "__main__":
    unittest.main()
