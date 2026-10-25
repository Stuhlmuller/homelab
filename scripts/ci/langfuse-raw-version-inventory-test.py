#!/usr/bin/env python3
"""Focused pagination and readback checks for the private Langfuse inventory."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).with_name("langfuse-raw-version-inventory.py")
SPEC = importlib.util.spec_from_file_location("langfuse_raw_versions", SOURCE)
SUT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUT)


class InventoryTests(unittest.TestCase):
    def test_protected_main_uses_dedicated_inventory_role(self):
        workflow_path = SOURCE.parents[2] / ".github/workflows/langfuse-raw-version-inventory.yml"
        workflow = json.loads(subprocess.check_output(["yq", "-o=json", ".", str(workflow_path)], text=True))
        job = workflow["jobs"]["inventory"]
        self.assertEqual(job["if"], "github.repository == 'Stuhlmuller/homelab' && github.ref == 'refs/heads/main'")
        self.assertEqual(job["environment"], {"name": "homelab-production"})
        self.assertEqual(job["permissions"], {"contents": "read", "id-token": "write"})

        steps = job["steps"]
        guard = next(index for index, step in enumerate(steps) if step["name"] == "Verify Current Main Before Credentials")
        credentials = next(index for index, step in enumerate(steps) if step["name"] == "Configure AWS Credentials")
        self.assertLess(guard, credentials)
        self.assertIn('test "$ACTUAL_SHA" = "$EXPECTED_SHA"', steps[guard]["run"])
        self.assertIn('test "$ACTUAL_SHA" = "$(gh api "repos/${GH_REPO}/git/ref/heads/main" --jq .object.sha)"', steps[guard]["run"])
        account = SUT.declared_bucket()["account_id"]
        self.assertEqual(steps[credentials]["with"]["role-to-assume"],
                         f"arn:aws:iam::{account}:role/homelab-langfuse-raw-inventory")
        self.assertEqual(steps[credentials]["with"]["role-duration-seconds"], 7200)

    def test_bucket_matches_infrastructure_and_workload(self):
        values = SUT.declared_bucket()
        self.assertEqual(values["bucket"],
                         f'homelab-langfuse-{values["account_id"]}-{values["region"]}')

    def test_all_pages_and_exact_versions_are_checked(self):
        calls = []

        def fake(*args):
            calls.append(args)
            if args[1] == "get-bucket-versioning":
                return {"Status": "Enabled"}
            if args[1] == "get-bucket-encryption":
                return {"ServerSideEncryptionConfiguration": {"Rules": [
                    {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}]}}
            if args[1] == "list-object-versions":
                if "--key-marker" not in args:
                    return {"IsTruncated": True,
                            "Versions": [{"Key": "raw/a", "VersionId": "v2", "Size": 7}],
                            "DeleteMarkers": [{"Key": "raw/old", "VersionId": "d1"}],
                            "NextKeyMarker": "raw/a", "NextVersionIdMarker": "v2"}
                self.assertEqual(args[args.index("--key-marker") + 1], "raw/a")
                self.assertEqual(args[args.index("--version-id-marker") + 1], "v2")
                return {"IsTruncated": False,
                        "Versions": [{"Key": "raw/b", "VersionId": "v1", "Size": 0}]}
            if args[1] == "head-object":
                return {"VersionId": args[args.index("--version-id") + 1],
                        "ContentLength": 7 if "raw/a" in args else 0,
                        "ServerSideEncryption": "aws:kms"}
            if args[1] == "get-object":
                self.assertEqual(args[-1], "/dev/null")
                size = 7 if "raw/a" in args else 0
                self.assertEqual("--range" in args, size > 0)
                return {"VersionId": args[args.index("--version-id") + 1],
                        "ContentLength": min(size, 1),
                        "ContentRange": f"bytes 0-0/{size}" if size else None,
                        "ServerSideEncryption": "aws:kms"}
            raise AssertionError(args)

        report = SUT.inventory(fake, "bucket", "123456789012")
        self.assertEqual(report["objects"], [
            {"key": "raw/a", "version": "v2", "bytes": 7},
            {"key": "raw/b", "version": "v1", "bytes": 0}])
        self.assertEqual(report["delete_markers"], [{"key": "raw/old", "version": "d1"}])
        self.assertEqual(sum(call[1] == "head-object" for call in calls), 2)
        self.assertEqual(sum(call[1] == "get-object" for call in calls), 2)
        self.assertTrue(all("--no-paginate" in call for call in calls if call[1] == "list-object-versions"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "inventory.json"
            digest = SUT.write_private(output, report)
            self.assertEqual(len(digest), 64)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(SUT.InventoryBlocked):
                SUT.write_private(output, report)

    def test_repeating_page_marker_blocks_incomplete_inventory(self):
        def fake(*args):
            if args[1] == "get-bucket-versioning":
                return {"Status": "Enabled"}
            if args[1] == "get-bucket-encryption":
                return {"ServerSideEncryptionConfiguration": {"Rules": [
                    {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}]}}
            return {"IsTruncated": True, "NextKeyMarker": "same", "NextVersionIdMarker": "v1"}

        with self.assertRaisesRegex(SUT.InventoryBlocked, "pagination"):
            SUT.inventory(fake, "bucket", "123456789012")

    def test_unreadable_or_changed_version_blocks_receipt(self):
        def fake(*args):
            if args[1] == "get-bucket-versioning":
                return {"Status": "Enabled"}
            if args[1] == "get-bucket-encryption":
                return {"ServerSideEncryptionConfiguration": {"Rules": [
                    {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}]}}
            if args[1] == "list-object-versions":
                return {"IsTruncated": False,
                        "Versions": [{"Key": "raw/a", "VersionId": "v1", "Size": 12}]}
            return {"VersionId": "v1", "ContentLength": 11,
                    "ServerSideEncryption": "aws:kms"}

        with self.assertRaisesRegex(SUT.InventoryBlocked, "readback"):
            SUT.inventory(fake, "bucket", "123456789012")


if __name__ == "__main__":
    unittest.main()
