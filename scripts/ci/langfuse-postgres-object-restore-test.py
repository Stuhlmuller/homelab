#!/usr/bin/env python3
"""Offline command-boundary checks for the protected exact-version restore."""

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/langfuse-postgres-object-restore.sh"
WORKFLOW = ROOT / ".github/workflows/langfuse-postgres-object-restore.yml"
BODY = b"PGDMPfixture"
SHA = "a" * 40
PVC = "e" * 36
PV = "1" * 36

MOCK = r'''#!/usr/bin/env python3
import base64, hashlib, json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
mode = os.environ.get("TEST_MODE", "good")
body = b"PGDMPfixture"
checksum = base64.b64encode(hashlib.sha256(body).digest()).decode()
metadata = {"VersionId": "version-1", "ChecksumSHA256": checksum,
            "ContentLength": len(body), "ServerSideEncryption": "aws:kms",
            "Metadata": {"source-revision": "a" * 40,
                         "source-pvc-uid": "e" * 36, "source-pv-uid": "1" * 36}}
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps([name, args]) + "\n")
if name == "gh":
    calls = sum(1 for line in Path(os.environ["TEST_LOG"]).read_text().splitlines()
                if json.loads(line)[0] == "gh")
    print("b" * 40 if mode == "main-advanced" or
          mode == "main-advanced-after-restore" and calls >= 2 else "a" * 40)
elif name == "aws":
    if "get-caller-identity" in args:
        print("716182248480")
    elif "get-bucket-versioning" in args:
        print("Enabled")
    elif "get-bucket-encryption" in args:
        print("aws:kms")
    elif "head-object" in args:
        if mode == "wrong-version": metadata["VersionId"] = "version-2"
        if mode == "wrong-checksum": metadata["ChecksumSHA256"] = "AAAA"
        if mode == "wrong-uid": metadata["Metadata"]["source-pvc-uid"] = "f" * 36
        print(json.dumps(metadata))
    elif "get-object" in args:
        assert args[args.index("--version-id") + 1] == "version-1"
        Path(args[-1]).write_bytes(b"corrupt" if mode == "corrupt-readback" else body)
        print(json.dumps(metadata))
    else:
        raise SystemExit("unexpected aws command")
elif name == "docker":
    if args[0] == "volume":
        print("volume-1")
    elif args[0] == "run":
        assert args[args.index("--network") + 1] == "none"
        print("container-1")
    elif args[0] == "exec":
        if "psql" in args: print("8")
    elif args[0] == "rm":
        pass
    else:
        raise SystemExit("unexpected docker command")
elif name == "kubectl":
    raise SystemExit("restore must not contact Kubernetes")
else:
    raise SystemExit("unknown mock binary")
'''


class ObjectRestoreTests(unittest.TestCase):
    def run_case(self, mode="good", overrides=None):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            for name in ("gh", "aws", "docker", "kubectl"):
                fake = path / name
                fake.write_text(MOCK)
                fake.chmod(0o755)
            log = path / "commands.jsonl"
            env = os.environ | {
                "PATH": f"{path}:{os.environ['PATH']}",
                "GITHUB_ACTIONS": "true",
                "GITHUB_REPOSITORY": "Stuhlmuller/homelab",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_SHA": SHA,
                "EXPECTED_SHA": SHA,
                "EXPECTED_PVC_UID": PVC,
                "EXPECTED_PV_UID": PV,
                "OBJECT_KEY": f"langfuse/postgresql/{SHA}/123/1/langfuse.dump",
                "OBJECT_VERSION": "version-1",
                "OBJECT_SHA256": hashlib.sha256(BODY).hexdigest(),
                "OBJECT_BYTES": str(len(BODY)),
                "GITHUB_RUN_ID": "456",
                "GITHUB_RUN_ATTEMPT": "1",
                "RUNNER_TEMP": temp,
                "TEST_LOG": str(log),
                "TEST_MODE": mode,
            }
            env.update(overrides or {})
            result = subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=30)
            commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            receipt = path / "langfuse-checkpoint-receipt"
            return result, commands, receipt.read_text() if receipt.exists() else ""

    def test_exact_version_restores_in_networkless_docker(self):
        result, commands, receipt = self.run_case()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tables=8", receipt)
        self.assertIn("version=version-1", receipt)
        self.assertTrue(any(name == "docker" and args[0] == "run" and
                            args[args.index("--network") + 1] == "none"
                            for name, args in commands))
        self.assertFalse(any(name == "kubectl" for name, _ in commands))

    def test_wrong_key_and_source_uid_rejected_before_credentials(self):
        for overrides in (
            {"OBJECT_KEY": f"langfuse/postgresql/{SHA}/123/2/langfuse.dump"},
            {"OBJECT_KEY": f"langfuse/postgresql/{'b' * 40}/123/1/langfuse.dump"},
            {"EXPECTED_PVC_UID": "not-a-uid"},
            {"OBJECT_VERSION": "null"},
        ):
            with self.subTest(overrides=overrides):
                result, commands, receipt = self.run_case(overrides=overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(commands, [])
                self.assertEqual(receipt, "")

    def test_wrong_version_checksum_or_uid_metadata_prevents_docker(self):
        for mode in ("wrong-version", "wrong-checksum", "wrong-uid", "corrupt-readback"):
            with self.subTest(mode=mode):
                result, commands, receipt = self.run_case(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(receipt, "")
                self.assertFalse(any(name == "docker" and args[0] == "run"
                                     for name, args in commands))

    def test_main_advance_prevents_restore_or_receipt(self):
        result, commands, receipt = self.run_case("main-advanced")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([name for name, _ in commands], ["gh"])
        self.assertEqual(receipt, "")
        result, commands, receipt = self.run_case("main-advanced-after-restore")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any(name == "docker" and "pg_restore" in args
                            for name, args in commands))
        self.assertEqual(receipt, "")

    def test_workflow_has_no_cluster_access_or_octelium_token(self):
        source = WORKFLOW.read_text()
        self.assertNotIn("OCTELIUM", source)
        self.assertNotIn("install-kubeconfig", source)
        self.assertIn("name: homelab-production", source)


if __name__ == "__main__":
    unittest.main()
