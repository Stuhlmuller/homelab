#!/usr/bin/env python3
"""Offline command-boundary checks for the protected one-shot checkpoint."""

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/langfuse-postgres-checkpoint.sh"
IMAGE = re.search(r"pgvector/pgvector:pg17@sha256:[0-9a-f]{64}",
                  (ROOT / "clusters/homelab/apps/langfuse/datastores.yaml").read_text()).group()

MOCK = r'''#!/usr/bin/env python3
import base64, hashlib, json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
mode = os.environ.get("TEST_MODE", "good")
image = os.environ["TEST_IMAGE"]
body = b"PGDMPfixture"
checksum = base64.b64encode(hashlib.sha256(body).digest()).decode()
metadata = {"VersionId": "version-1", "ChecksumSHA256": checksum,
            "ContentLength": len(body), "ServerSideEncryption": "aws:kms"}
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps([name, args]) + "\n")
if name == "gh":
    print("b" * 40 if mode == "main-advanced" else os.environ["GITHUB_SHA"])
elif name == "kubectl":
    if args[:2] == ["auth", "can-i"]:
        print("no" if mode == "deny-exec" and "pods/exec" in args else "yes")
    elif "get" in args and "deployment" in args:
        print(json.dumps({"metadata": {"uid": "c" * 36, "generation": 1}, "spec": {"replicas": 1,
              "template": {"spec": {"containers": [{"name": "postgres", "image": image,
              "volumeMounts": [{"name": "data", "mountPath": "/var/lib/postgresql/data"}]}],
              "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "langfuse-postgres-data"}}]}}},
              "status": {"readyReplicas": 1, "updatedReplicas": 1, "observedGeneration": 1}}))
    elif "get" in args and "pods" in args:
        pod = {"metadata": {"name": "langfuse-postgres-abc", "uid": "a" * 36,
               "ownerReferences": [{"controller": True, "kind": "ReplicaSet",
                                    "name": "langfuse-postgres-abc", "uid": "b" * 36}]},
               "status": {"phase": "Running", "containerStatuses": [{"name": "postgres", "ready": True}]},
               "spec": {"containers": [{"name": "postgres", "image": image,
                       "volumeMounts": [{"name": "data", "mountPath": "/var/lib/postgresql/data"}]}],
                        "volumes": [{"name": "data", "persistentVolumeClaim":
                                     {"claimName": "wrong-data" if mode == "wrong-pvc" else "langfuse-postgres-data"}}]}}
        print(json.dumps({"items": [pod, pod] if mode == "two-pods" else [pod]}))
    elif "get" in args and "replicaset" in args:
        print(json.dumps({"metadata": {"uid": "b" * 36,
              "ownerReferences": [{"controller": True, "kind": "Deployment",
                                   "name": "langfuse-postgres",
                                   "uid": "d" * 36 if mode == "wrong-owner" else "c" * 36}]}}))
    elif "exec" in args and "pg_dump" in args:
        sys.stdout.buffer.write(body)
    elif "exec" in args and "psql" in args:
        print("14284467")
    else:
        raise SystemExit("unexpected kubectl command")
elif name == "aws":
    if "get-caller-identity" in args:
        print("716182248480")
    elif "get-bucket-versioning" in args:
        print("Enabled")
    elif "get-bucket-encryption" in args:
        print("aws:kms")
    elif "list-object-versions" in args:
        print(json.dumps({"Versions": [], "DeleteMarkers": []}))
    elif "put-object" in args:
        assert "--if-none-match" in args and args[args.index("--if-none-match") + 1] == "*"
        assert Path(args[args.index("--body") + 1]).read_bytes() == body
        print(json.dumps({"VersionId": "version-1"}))
    elif "head-object" in args:
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
        assert "none" == args[args.index("--network") + 1]
        assert image == args[-1]
        print("container-1")
    elif args[0] == "exec":
        if "psql" in args:
            print("8")
    elif args[0] == "rm":
        pass
    else:
        raise SystemExit("unexpected docker command")
else:
    raise SystemExit("unknown mock binary")
'''


class CheckpointTests(unittest.TestCase):
    def run_case(self, mode="good", expected_sha=None):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            for name in ("gh", "kubectl", "aws", "docker"):
                fake = path / name
                fake.write_text(MOCK)
                fake.chmod(0o755)
            log = path / "commands.jsonl"
            sha = "a" * 40
            env = os.environ | {
                "PATH": f"{path}:{os.environ['PATH']}",
                "GITHUB_ACTIONS": "true",
                "GITHUB_REPOSITORY": "Stuhlmuller/homelab",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_SHA": sha,
                "EXPECTED_SHA": expected_sha or sha,
                "GITHUB_RUN_ID": "123",
                "GITHUB_RUN_ATTEMPT": "1",
                "RUNNER_TEMP": temp,
                "TEST_IMAGE": IMAGE,
                "TEST_MODE": mode,
                "TEST_LOG": str(log),
            }
            result = subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=30)
            commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            receipt = path / "langfuse-checkpoint-receipt"
            return result, commands, receipt.read_text() if receipt.exists() else ""

    def test_exact_current_main_restores_downloaded_version_without_network(self):
        result, commands, receipt = self.run_case()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("version=version-1", receipt)
        self.assertIn("tables=8", receipt)
        self.assertTrue(any(name == "aws" and "--if-none-match" in args
                            for name, args in commands))
        self.assertTrue(any(name == "docker" and args[0] == "run" and "--network" in args
                            for name, args in commands))

    def test_restore_readiness_uses_tcp_loopback(self):
        result, commands, _ = self.run_case()
        self.assertEqual(result.returncode, 0, result.stderr)
        probes = [args for name, args in commands
                  if name == "docker" and args[:3] == ["exec", "container-1", "pg_isready"]]
        self.assertEqual(len(probes), 1)
        self.assertIn("-h", probes[0])
        self.assertEqual(probes[0][probes[0].index("-h") + 1], "127.0.0.1")

    def test_multiple_source_pods_prevent_dump_and_upload(self):
        result, commands, receipt = self.run_case("two-pods")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any("pg_dump" in args or "put-object" in args for _, args in commands))

    def test_missing_ci_exec_right_prevents_dump_and_upload(self):
        result, commands, receipt = self.run_case("deny-exec")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any("pg_dump" in args or "put-object" in args for _, args in commands))

    def test_wrong_data_claim_prevents_dump_and_upload(self):
        result, commands, receipt = self.run_case("wrong-pvc")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any("pg_dump" in args or "put-object" in args for _, args in commands))

    def test_wrong_replica_set_owner_prevents_dump_and_upload(self):
        result, commands, receipt = self.run_case("wrong-owner")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any("pg_dump" in args or "put-object" in args for _, args in commands))

    def test_corrupt_exact_version_prevents_restore_receipt(self):
        result, commands, receipt = self.run_case("corrupt-readback")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any(name == "docker" and args[0] == "run" for name, args in commands))

    def test_stale_dispatch_prevents_credentialed_calls(self):
        result, commands, receipt = self.run_case(expected_sha="b" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertEqual(commands, [])

    def test_advanced_main_prevents_credentialed_calls(self):
        result, commands, receipt = self.run_case("main-advanced")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertEqual([name for name, _ in commands], ["gh"])


if __name__ == "__main__":
    unittest.main()
