#!/usr/bin/env python3
"""Offline failure fixtures for a timed-out legacy restore continuation."""

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "scripts/ci/openclaw-enterprise-operations.sh").read_text()
spec = importlib.util.spec_from_file_location(
    "oce_resume_provenance", ROOT / "scripts/ci/openclaw-enterprise-resume-provenance.py")
PROVENANCE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PROVENANCE)
REF = "a" * 40 + "/123"


def function(name):
    return name + "() {\n" + SOURCE.split(name + "() {\n", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


def cli_log(archive_ref, cached=False):
    if cached:
        label = "Run Legacy Stage"
        times = ("\ufeff2026-10-23T16:53:06.0258833Z", "2026-10-23T16:53:06.0353791Z",
                 "2026-10-23T16:53:06.0354590Z", "2026-10-23T16:53:06.0355923Z",
                 "2026-10-23T22:53:29.0245903Z")
    else:
        label = "UNKNOWN STEP"
        times = ("2026-10-23T16:53:06.0258845Z", "2026-10-23T16:53:06.0354002Z",
                 "2026-10-23T16:53:06.0354592Z", "2026-10-23T16:53:06.0355926Z",
                 "2026-10-23T22:53:29.0245920Z")
    prefix = "Protected Legacy Retention\t" + label + "\t"
    return "\n".join(prefix + line for line in (
        times[0] + ' ##[group]Run private_log="$(mktemp)"',
        times[1] + "   RUN_STAGE: prepare-restore",
        times[2] + "   ARCHIVE_REF: " + archive_ref,
        times[3] + " ##[endgroup]",
        times[4] + " ##[error]The operation was canceled.",
    ))


class ResumeProvenance(unittest.TestCase):
    def test_prior_source_declares_exact_six_hour_legacy_limit(self):
        workflow = "jobs:\n  legacy:\n    timeout-minutes: 360\n  enterprise:\n    timeout-minutes: 150\n"
        PROVENANCE.require_legacy_timeout(workflow)
        for source in (workflow.replace("360", "359"),
                       workflow.replace("  legacy:", "  backup:"),
                       workflow.replace("  enterprise:", "    timeout-minutes: 360\n  enterprise:")):
            with self.subTest(source=source), self.assertRaises(PROVENANCE.Blocked):
                PROVENANCE.require_legacy_timeout(source)

    def test_prior_run_requires_one_terminal_cancelled_protected_attempt(self):
        run = {"id": 123, "event": "workflow_dispatch", "path": PROVENANCE.WORKFLOW,
               "head_branch": "main", "status": "completed", "conclusion": "cancelled",
               "run_attempt": 1, "head_sha": "a" * 40}
        self.assertEqual(PROVENANCE.parse_run(run, "123"), "a" * 40)
        for changed in ({"id": 124}, {"conclusion": "success"}, {"status": "in_progress"},
                        {"run_attempt": 2}, {"path": "unrelated.yml"},
                        {"event": "push"}, {"head_sha": "bad"}):
            with self.subTest(changed=changed), self.assertRaises(PROVENANCE.Blocked):
                PROVENANCE.parse_run({**run, **changed}, "123")
        job = {"id": PROVENANCE.PRIOR_JOB_ID, "name": PROVENANCE.JOB,
               "status": "completed", "conclusion": "cancelled",
               "started_at": PROVENANCE.PRIOR_JOB_STARTED_AT,
               "completed_at": PROVENANCE.PRIOR_JOB_COMPLETED_AT,
               "steps": [{"name": PROVENANCE.STAGE_STEP, "number": 7,
                          "status": "completed", "conclusion": "cancelled",
                          "started_at": "2026-10-23T16:53:06Z",
                          "completed_at": "2026-10-23T22:53:29Z"}]}
        self.assertEqual(PROVENANCE.parse_job({"total_count": 1, "jobs": [job]}),
                         PROVENANCE.PRIOR_JOB_ID)
        for jobs in ({"total_count": 0, "jobs": []},
                     {"total_count": 2, "jobs": [job, job]},
                     {"total_count": 2, "jobs": [job]},
                     {"total_count": 1, "jobs": [{**job, "conclusion": "success"}]},
                     {"total_count": 1, "jobs": [{**job, "id": 999}]},
                     {"total_count": 1, "jobs": [{**job, "completed_at": "2026-10-23T17:53:32Z"}]},
                     {"total_count": 1, "jobs": [{**job, "steps": []}]},
                     {"total_count": 1, "jobs": [{**job, "steps": job["steps"] * 2}]},
                     {"total_count": 1, "jobs": [{**job, "steps": [
                         {**job["steps"][0], "conclusion": "success"}]}]},
                     {"total_count": 1, "jobs": [{**job, "steps": [
                         {**job["steps"][0], "started_at": "2026-10-23T16:53:07Z"}]}]}):
            with self.subTest(jobs=jobs), self.assertRaises(PROVENANCE.Blocked):
                PROVENANCE.parse_job(jobs)

    def test_protected_log_binds_exact_stage_and_publication_ref(self):
        log = cli_log(REF)
        PROVENANCE.parse_log(log, REF)
        PROVENANCE.parse_log(cli_log(REF, cached=True), REF)
        lines = log.splitlines()
        for changed in (lines + [lines[1]],
                        lines + [lines[-1]],
                        [lines[0], lines[1], lines[2].replace(REF, "b" * 40 + "/123"), *lines[3:]],
                        [lines[0], lines[1].replace("prepare-restore", "verify"), *lines[2:]],
                        lines[:1],
                        lines[:2],
                        [*lines[:-1], lines[-1].replace("22:53:29", "17:53:29")],
                        [*lines[:-1], lines[-1].replace("0245920", "024592")],
                        [lines[0].replace('Run private_log="$(mktemp)"', "Run untrusted"), *lines[1:]],
                        [lines[0], lines[3], lines[1], lines[2], lines[4]],
                        [*lines, lines[0]],
                        [*lines, lines[1].replace("UNKNOWN STEP", "Run Legacy Stage")],
                        [lines[0], lines[1], cli_log(REF, cached=True).splitlines()[2], *lines[3:]],
                        [*lines[:-1], lines[-1].replace("UNKNOWN STEP", "Other Step")],
                        [lines[0].replace("Protected Legacy Retention", "Other Job"), *lines[1:]]):
            with self.subTest(log=changed), self.assertRaises(PROVENANCE.Blocked):
                PROVENANCE.parse_log("\n".join(changed), REF)

    def test_valid_provenance_writes_exclusive_private_receipt(self):
        run = {"id": 123, "event": "workflow_dispatch", "path": PROVENANCE.WORKFLOW,
               "head_branch": "main", "status": "completed", "conclusion": "cancelled",
               "run_attempt": 1, "head_sha": "a" * 40}
        jobs = {"total_count": 1, "jobs": [{"id": PROVENANCE.PRIOR_JOB_ID,
                                              "name": PROVENANCE.JOB, "status": "completed",
                                              "conclusion": "cancelled",
                                              "started_at": PROVENANCE.PRIOR_JOB_STARTED_AT,
                                              "completed_at": PROVENANCE.PRIOR_JOB_COMPLETED_AT,
                                              "steps": [{"name": PROVENANCE.STAGE_STEP,
                                                         "number": 7, "status": "completed",
                                                         "conclusion": "cancelled",
                                                         "started_at": "2026-10-23T16:53:06Z",
                                                         "completed_at": "2026-10-23T22:53:29Z"}]}]}
        log = cli_log(REF)
        def command(*args, **_kwargs):
            if args[:3] == ("git", "rev-parse", "HEAD"):
                return ("b" * 40 + "\n").encode()
            if args[:3] == ("gh", "api", "repos/Stuhlmuller/homelab/git/ref/heads/main"):
                return ("b" * 40 + "\n").encode()
            if args[:3] == ("gh", "api", "repos/Stuhlmuller/homelab/actions/runs/123"):
                return json.dumps(run).encode()
            if args[:3] == ("gh", "api", "repos/Stuhlmuller/homelab/actions/runs/123/jobs?per_page=100"):
                return json.dumps(jobs).encode()
            if args == ("gh", "run", "view", "123", "--job", str(PROVENANCE.PRIOR_JOB_ID),
                        "--log", "--repo", "Stuhlmuller/homelab"):
                return log.encode()
            raise AssertionError(args)
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.json"
            argv = ["--prior-run-id", "123", "--archive-ref", REF,
                    "--current-sha", "b" * 40, "--receipt", str(receipt)]
            env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "Stuhlmuller/homelab",
                   "GITHUB_SHA": "b" * 40, "GH_TOKEN": "fixture"}
            with patch.dict(os.environ, env), patch.object(PROVENANCE, "command", side_effect=command), \
                 patch.object(PROVENANCE, "prove_source") as source, \
                 patch.object(PROVENANCE, "PRIOR_RUN_ID", "123"), \
                 patch.object(PROVENANCE, "PRIOR_SOURCE_SHA", "a" * 40), \
                 patch.object(PROVENANCE, "PUBLISHED_ARCHIVE_REF", REF):
                self.assertEqual(PROVENANCE.main(argv), 0)
                source.assert_called_once_with("a" * 40, "b" * 40)
                self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads(receipt.read_text()),
                                 {"priorRunId": "123", "priorSourceSha": "a" * 40,
                                  "archiveRef": REF, "currentSha": "b" * 40})
                self.assertEqual(PROVENANCE.main(argv), 1)
                self.assertEqual(json.loads(receipt.read_text())["archiveRef"], REF)
                receipt.unlink()
                wrong = argv.copy()
                wrong[wrong.index("--archive-ref") + 1] = "b" * 40 + "/123"
                self.assertEqual(PROVENANCE.main(wrong), 1)
                self.assertFalse(receipt.exists())
                wrong_run = argv.copy()
                wrong_run[wrong_run.index("--prior-run-id") + 1] = "124"
                self.assertEqual(PROVENANCE.main(wrong_run), 1)
                run["head_sha"] = "c" * 40
                self.assertEqual(PROVENANCE.main(argv), 1)
                self.assertFalse(receipt.exists())

    def test_failure_reports_only_fixed_provenance_boundary(self):
        run = {"id": 123, "event": "workflow_dispatch", "path": PROVENANCE.WORKFLOW,
               "head_branch": "main", "status": "completed", "conclusion": "cancelled",
               "run_attempt": 1, "head_sha": "a" * 40}
        jobs = {"total_count": 1, "jobs": [{"id": PROVENANCE.PRIOR_JOB_ID,
                                              "name": PROVENANCE.JOB, "status": "completed",
                                              "conclusion": "cancelled",
                                              "started_at": PROVENANCE.PRIOR_JOB_STARTED_AT,
                                              "completed_at": PROVENANCE.PRIOR_JOB_COMPLETED_AT,
                                              "steps": [{"name": PROVENANCE.STAGE_STEP,
                                                         "number": 7, "status": "completed",
                                                         "conclusion": "cancelled",
                                                         "started_at": "2026-10-23T16:53:06Z",
                                                         "completed_at": "2026-10-23T22:53:29Z"}]}]}
        log = cli_log(REF)
        outputs = [("b" * 40 + "\n").encode(), ("b" * 40 + "\n").encode(),
                   json.dumps(run).encode(), json.dumps(jobs).encode(), log.encode()]
        cases = (("input", None), ("current-main", 0), ("prior-run", 2),
                 ("prior-job", 3), ("prior-log-fetch", 4),
                 ("prior-log-match", None), ("source", None), ("receipt", None))
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.json"
            argv = ["--prior-run-id", "123", "--archive-ref", REF,
                    "--current-sha", "b" * 40, "--receipt", str(receipt)]
            env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "Stuhlmuller/homelab",
                   "GITHUB_SHA": "b" * 40, "GH_TOKEN": "fixture"}
            for boundary, failed_at in cases:
                with self.subTest(boundary=boundary):
                    calls = iter(enumerate(outputs))
                    def command(*_args, **_kwargs):
                        index, output = next(calls)
                        if index == failed_at:
                            raise PROVENANCE.Blocked("sensitive failure detail")
                        return output
                    if boundary == "receipt":
                        receipt.write_text("prior receipt")
                    if boundary == "prior-log-match":
                        outputs[4] = b"wrong log fixture"
                    stderr = io.StringIO()
                    with patch.dict(os.environ, {**env, "GH_TOKEN": "" if boundary == "input" else "fixture"}), \
                         patch.object(PROVENANCE, "command", side_effect=command), \
                         patch.object(PROVENANCE, "prove_source", side_effect=(
                             PROVENANCE.Blocked("sensitive failure detail")
                             if boundary == "source" else None)), \
                         patch.object(PROVENANCE, "PRIOR_RUN_ID", "123"), \
                         patch.object(PROVENANCE, "PRIOR_SOURCE_SHA", "a" * 40), \
                         patch.object(PROVENANCE, "PUBLISHED_ARCHIVE_REF", REF), \
                         redirect_stderr(stderr):
                        self.assertEqual(PROVENANCE.main(argv), 1)
                    self.assertEqual(stderr.getvalue(),
                                     f"Prior restore provenance blocked: {boundary}\n")
                    if boundary != "receipt":
                        self.assertFalse(receipt.exists())
                    receipt.unlink(missing_ok=True)
                    outputs[4] = log.encode()


class ResumeCache(unittest.TestCase):
    def shell(self, code, directory):
        env = dict(os.environ)
        if sys.platform == "darwin":
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir(exist_ok=True)
            shim = bin_dir / "stat"
            shim.write_text("""#!/usr/bin/env python3
import os, stat, sys
assert len(sys.argv) == 4 and sys.argv[1] == '-c'
item = os.lstat(sys.argv[3])
values = {'%d': str(item.st_dev), '%i': str(item.st_ino),
          '%s': str(item.st_size), '%Y': str(int(item.st_mtime)),
          '%a': format(stat.S_IMODE(item.st_mode), 'o')}
template = sys.argv[2]
for key, value in values.items():
    template = template.replace(key, value)
print(template)
""")
            shim.chmod(0o755)
            env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
        return subprocess.run(["bash", "-c", "set -euo pipefail\nreader=()\n"
                               "PRIOR_RUN_ID=123\n" + code], cwd=directory,
                              env=env, capture_output=True, text=True, timeout=10, check=False)

    def test_cached_archive_requires_exact_regular_private_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "offsite-123"
            cache.mkdir(mode=0o700)
            archive = cache / "legacy.tar.gz"
            archive.write_bytes(b"correct bytes")
            archive.chmod(0o600)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            call = f'verify_cached_restore_file "{cache}" legacy.tar.gz 13 {digest}\n'
            code = function("verify_cached_restore_file") + call
            self.assertEqual(self.shell(code, directory).returncode, 0)
            for changed in ("wrong-size", "wrong-digest", "symlink", "loose-mode"):
                with self.subTest(changed=changed):
                    archive.unlink(missing_ok=True)
                    archive.write_bytes(b"correct bytes")
                    archive.chmod(0o600)
                    candidate = code
                    if changed == "wrong-size":
                        candidate = candidate.replace("legacy.tar.gz 13 ", "legacy.tar.gz 12 ")
                    elif changed == "wrong-digest":
                        candidate = candidate.replace(digest, "0" * 64)
                    elif changed == "symlink":
                        archive.unlink()
                        archive.symlink_to(cache / "other")
                    else:
                        archive.chmod(0o644)
                    self.assertNotEqual(self.shell(candidate, directory).returncode, 0)

    def test_marker_wait_accepts_only_stable_exact_success(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "verify-123.state"
            code = function("read_prior_restore_marker").replace(
                '"/private/legacy/verify-${PRIOR_RUN_ID}.state"', f'"{marker}"')
            code += function("wait_prior_restore").replace("attempt < 120", "attempt < 2").replace(
                "sleep 30", "sleep 0.01").replace("sleep 1", "sleep 0.01")
            self.assertNotEqual(self.shell(code + "wait_prior_restore\n", directory).returncode, 0)
            for value, allowed in ((b"success\n", True), (b"failure\n", False),
                                   (b"success", False), (b"success\nfailure\n", False),
                                   (b"unknown\n", False), (b"", False)):
                with self.subTest(value=value):
                    marker.unlink(missing_ok=True)
                    marker.write_bytes(value)
                    marker.chmod(0o600)
                    result = self.shell(code + "wait_prior_restore\n", directory)
                    self.assertEqual(result.returncode == 0, allowed, result.stderr)
            marker.unlink()
            marker.symlink_to(Path(directory) / "other")
            self.assertNotEqual(self.shell(code + "wait_prior_restore\n", directory).returncode, 0)

    def test_completed_report_requires_promoted_private_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            rehearsal = Path(directory) / "rehearsal-123"
            rehearsal.mkdir(mode=0o700)
            tree = rehearsal / "tree"
            tree.mkdir()
            (tree / "local").mkdir()
            (tree / "nas").mkdir()
            report = rehearsal / "completed.json"
            report.write_text('{"format":1}\n')
            report.chmod(0o600)
            code = function("read_prior_restore_report") + f'read_prior_restore_report "{rehearsal}"\n'
            self.assertEqual(self.shell(code, directory).stdout, '{"format":1}\n')
            (tree / "nas").rmdir()
            self.assertNotEqual(self.shell(code, directory).returncode, 0)
            (tree / "nas").symlink_to(tree / "local")
            self.assertNotEqual(self.shell(code, directory).returncode, 0)
            (tree / "nas").unlink()
            (tree / "nas").mkdir()
            report.chmod(0o644)
            self.assertNotEqual(self.shell(code, directory).returncode, 0)


if __name__ == "__main__":
    unittest.main()
