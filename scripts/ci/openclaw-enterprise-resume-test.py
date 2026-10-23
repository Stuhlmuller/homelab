#!/usr/bin/env python3
"""Offline failure fixtures for a timed-out legacy restore continuation."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
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


class ResumeProvenance(unittest.TestCase):
    def test_prior_run_requires_one_timed_out_protected_attempt(self):
        run = {"id": 123, "event": "workflow_dispatch", "path": PROVENANCE.WORKFLOW,
               "head_branch": "main", "status": "completed", "conclusion": "timed_out",
               "run_attempt": 1, "head_sha": "a" * 40}
        self.assertEqual(PROVENANCE.parse_run(run, "123"), "a" * 40)
        for changed in ({"id": 124}, {"conclusion": "success"}, {"status": "in_progress"},
                        {"run_attempt": 2}, {"path": "unrelated.yml"},
                        {"event": "push"}, {"head_sha": "bad"}):
            with self.subTest(changed=changed), self.assertRaises(PROVENANCE.Blocked):
                PROVENANCE.parse_run({**run, **changed}, "123")
        job = {"id": 456, "name": PROVENANCE.JOB, "status": "completed",
               "conclusion": "timed_out"}
        self.assertEqual(PROVENANCE.parse_job({"total_count": 1, "jobs": [job]}), 456)
        for jobs in ({"total_count": 0, "jobs": []},
                     {"total_count": 2, "jobs": [job, job]},
                     {"total_count": 2, "jobs": [job]},
                     {"total_count": 1, "jobs": [{**job, "conclusion": "success"}]}):
            with self.subTest(jobs=jobs), self.assertRaises(PROVENANCE.Blocked):
                PROVENANCE.parse_job(jobs)

    def test_protected_log_binds_exact_stage_and_publication_ref(self):
        prefix = "Protected Legacy Retention\tRun Legacy Stage\t2026-10-23T14:12:35.4394893Z   "
        lines = [prefix + "RUN_STAGE: prepare-restore", prefix + "ARCHIVE_REF: " + REF]
        PROVENANCE.parse_log("\n".join(lines), REF)
        for log in ("\n".join(lines + [lines[0]]),
                    "\n".join([lines[0], prefix + "ARCHIVE_REF: " + "b" * 40 + "/123"]),
                    "\n".join([prefix + "RUN_STAGE: verify", lines[1]]),
                    "\n".join(lines[:1]),
                    "\n".join([line.replace("Run Legacy Stage", "Run Untrusted Step") for line in lines])):
            with self.subTest(log=log), self.assertRaises(PROVENANCE.Blocked):
                PROVENANCE.parse_log(log, REF)

    def test_valid_provenance_writes_exclusive_private_receipt(self):
        run = {"id": 123, "event": "workflow_dispatch", "path": PROVENANCE.WORKFLOW,
               "head_branch": "main", "status": "completed", "conclusion": "timed_out",
               "run_attempt": 1, "head_sha": "a" * 40}
        jobs = {"total_count": 1, "jobs": [{"id": 456, "name": PROVENANCE.JOB,
                                              "status": "completed", "conclusion": "timed_out"}]}
        prefix = "Protected Legacy Retention\tRun Legacy Stage\t2026-10-23T14:12:35.4394893Z   "
        log = prefix + "RUN_STAGE: prepare-restore\n" + prefix + "ARCHIVE_REF: " + REF
        def command(*args, **_kwargs):
            if args[:3] == ("git", "rev-parse", "HEAD"):
                return ("b" * 40 + "\n").encode()
            if args[:3] == ("gh", "api", "repos/Stuhlmuller/homelab/git/ref/heads/main"):
                return ("b" * 40 + "\n").encode()
            if args[:3] == ("gh", "api", "repos/Stuhlmuller/homelab/actions/runs/123"):
                return json.dumps(run).encode()
            if args[:3] == ("gh", "api", "repos/Stuhlmuller/homelab/actions/runs/123/jobs?per_page=100"):
                return json.dumps(jobs).encode()
            if args[:3] == ("gh", "run", "view"):
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


if __name__ == "__main__":
    unittest.main()
