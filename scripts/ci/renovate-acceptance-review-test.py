#!/usr/bin/env python3
"""Private review delivery rejects unsafe files and never puts values in command args."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "renovate_acceptance_review", ROOT / "scripts/renovate-acceptance-review.py")
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)


class ReviewDeliveryTests(unittest.TestCase):
    def test_private_review_file_is_bounded_and_owner_only(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "review.json"
            raw = json.dumps({"schema": 1, "owner": "Stuhlmuller",
                              "repositories": [], "classifications": []}).encode()
            source.write_bytes(raw)
            source.chmod(0o600)
            self.assertEqual(REVIEW.private_review(str(source)), raw)
            source.chmod(0o644)
            with self.assertRaises(REVIEW.Failure):
                REVIEW.private_review(str(source))
            source.chmod(0o600)
            link = Path(directory) / "link.json"
            link.symlink_to(source)
            with self.assertRaises(REVIEW.Failure):
                REVIEW.private_review(str(link))
            source.write_bytes(b"x" * (REVIEW.LIMIT + 1))
            with self.assertRaises(REVIEW.Failure):
                REVIEW.private_review(str(source))

    def test_secret_creation_passes_private_value_only_on_stdin(self):
        raw = b'{"schema":1,"owner":"Stuhlmuller"}'
        existing = {"data": {"review.json": "eyJzY2hlbWEiOjEsIm93bmVyIjoiU3R1aGxtdWxsZXIifQ=="}}
        with (mock.patch.object(REVIEW, "secret", side_effect=[None, existing]),
              mock.patch.object(REVIEW, "command", return_value="") as run,
              mock.patch("builtins.print")):
            REVIEW.install(raw, True)
        args = run.call_args.args
        self.assertEqual(args, ("kubectl", "create", "-f", "-"))
        self.assertNotIn(raw.decode(), " ".join(args))
        manifest = json.loads(run.call_args.kwargs["input_data"])
        self.assertEqual(manifest["metadata"], {
            "name": REVIEW.SECRET, "namespace": REVIEW.NAMESPACE})
        self.assertIs(manifest["immutable"], True)
        self.assertEqual(manifest["data"]["review.json"], existing["data"]["review.json"])

    def test_private_review_rejects_other_checkout_and_linked_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "other-repository"
            worktree = Path(directory) / "linked-worktree"
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            subprocess.run(["git", "-C", str(repository), "-c", "user.name=Test",
                            "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
                            "commit", "--allow-empty", "-q", "-m", "seed"], check=True)
            subprocess.run(["git", "-C", str(repository), "worktree", "add", "-q",
                            "-b", "test-worktree", str(worktree)], check=True)
            raw = json.dumps({"schema": 1, "owner": "Stuhlmuller",
                              "repositories": [], "classifications": []}).encode()
            for checkout in (repository, worktree):
                source = checkout / "review.json"
                source.write_bytes(raw)
                source.chmod(0o600)
                with self.assertRaises(REVIEW.Failure):
                    REVIEW.private_review(str(source))

    def test_retirement_rejects_a_successful_job_from_before_delivery(self):
        existing = {"metadata": {"creationTimestamp": "2026-10-19T19:00:00Z"}}
        job = {"metadata": {"name": REVIEW.JOB},
               "status": {"startTime": "2026-10-19T18:00:00Z", "succeeded": 1}}
        with (mock.patch.object(REVIEW, "secret", return_value=existing),
              mock.patch.object(REVIEW, "command", return_value=json.dumps(job))):
            with self.assertRaises(REVIEW.Failure):
                REVIEW.retire(True)


if __name__ == "__main__":
    unittest.main()
