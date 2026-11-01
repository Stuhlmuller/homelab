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
IMAGE = re.search(r"harbor\.stinkyboi\.com/mirror/docker\.io/pgvector/pgvector:[^@\s]+@sha256:[0-9a-f]{64}",
                  (ROOT / "clusters/homelab/apps/langfuse/datastores.yaml").read_text()).group()
PODS_PATH = ("/api/v1/namespaces/langfuse/pods?labelSelector="
             "app.kubernetes.io%2Fname%3Dlangfuse%2C"
             "app.kubernetes.io%2Finstance%3Dlangfuse%2C"
             "app.kubernetes.io%2Fcomponent%3Dpostgresql")

MOCK = r'''#!/usr/bin/env python3
import base64, hashlib, json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
mode = os.environ.get("TEST_MODE", "good")
image = os.environ["TEST_IMAGE"]
runtime_image = "pgvector/pgvector:pg17@sha256:" + "0" * 64 if mode == "upstream-pod" else image
body = b"PGDMPfixture"
checksum = base64.b64encode(hashlib.sha256(body).digest()).decode()
metadata = {"VersionId": "version-1", "ChecksumSHA256": checksum,
            "ContentLength": len(body), "ServerSideEncryption": "aws:kms",
            "Metadata": {"source-revision": os.environ["GITHUB_SHA"],
                         "source-pvc-uid": "e" * 36, "source-pv-uid": "1" * 36}}
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps([name, args]) + "\n")
if name == "gh":
    calls = sum(1 for line in Path(os.environ["TEST_LOG"]).read_text().splitlines()
                if json.loads(line)[0] == "gh")
    advanced = (mode == "main-advanced" or
                mode == "main-advanced-after-dump" and calls >= 2 or
                mode == "main-advanced-after-upload" and calls >= 3)
    print("b" * 40 if advanced else os.environ["GITHUB_SHA"])
elif name == "git":
    if args == ["rev-parse", "--show-toplevel"]:
        print(os.environ["TEST_ROOT"])
    elif args == ["status", "--porcelain", "--untracked-files=all"]:
        if mode == "dirty-checkout": print(" M scripts/ci/langfuse-postgres-checkpoint.sh")
    elif args == ["rev-parse", "HEAD"]:
        print("b" * 40 if mode == "stale-local" else os.environ["GITHUB_SHA"])
    else:
        raise SystemExit("unexpected git command")
elif name == "kubectl":
    if args == ["config", "view", "--minify", "--raw", "-o", "json"]:
        print(json.dumps({"clusters": [{"cluster": {
            "server": "https://10.1.0.199:6443",
            "insecure-skip-tls-verify": mode == "insecure-kubeconfig",
            "certificate-authority-data": "CA"}}]}))
    elif args[:2] == ["auth", "can-i"]:
        print("no" if (mode == "deny-exec" and "pods/exec" in args) or
              (mode == "deny-pod-list" and args[2:4] == ["list", "pods"]) or
              (mode == "deny-pv" and "persistentvolumes" in args) else "yes")
    elif "get" in args and "deployment" in args:
        print(json.dumps({"metadata": {"uid": "c" * 36, "generation": 1}, "spec": {"replicas": 1,
              "template": {"spec": {"containers": [{"name": "postgres", "image": runtime_image,
              "volumeMounts": [{"name": "data", "mountPath": "/var/lib/postgresql/data"}]}],
              "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "langfuse-postgres-data"}}]}}},
              "status": {"readyReplicas": 1, "updatedReplicas": 1, "observedGeneration": 1}}))
    elif "get" in args and "pvc" in args:
        claim_uid = "f" * 36 if mode == "claim-replaced" and Path(os.environ["TEST_DUMPED"]).exists() else "e" * 36
        print(json.dumps({"kind": "PersistentVolumeClaim",
              "metadata": {"namespace": "langfuse", "name": "langfuse-postgres-data", "uid": claim_uid,
                           "deletionTimestamp": "2026-10-24T00:00:00Z" if mode == "pvc-deleting" else None},
              "spec": {"storageClassName": "nfs-default", "accessModes": ["ReadWriteOnce"],
                       "volumeName": "pvc-wrong" if mode == "wrong-pv-name" else "pvc-" + claim_uid},
              "status": {"phase": "Bound"}}))
    elif "get" in args and "pv" in args:
        print(json.dumps({"kind": "PersistentVolume",
              "metadata": {"name": "pvc-" + "e" * 36, "uid": "1" * 36,
                           "deletionTimestamp": "2026-10-24T00:00:00Z" if mode == "pv-deleting" else None},
              "spec": {"storageClassName": "nfs-default", "persistentVolumeReclaimPolicy": "Retain",
                       "nfs": {"server": "10.1.0.2", "path": "/homelab/wrong-export"
                               if mode == "wrong-nfs-path" else
                               "/homelab/langfuse-langfuse-postgres-data-pvc-" + "e" * 36},
                       "claimRef": {"namespace": "langfuse", "name": "langfuse-postgres-data",
                                    "uid": "2" * 36 if mode == "wrong-pv-owner" else "e" * 36}},
              "status": {"phase": "Bound"}}))
    elif args[:2] == ["get", "--raw"] or ("get" in args and "pods" in args):
        raw = args[:2] == ["get", "--raw"]
        if raw:
            assert args == ["get", "--raw", os.environ["TEST_PODS_PATH"]]
        pod = {"metadata": {"name": "langfuse-postgres-abc", "uid": "a" * 36,
               "ownerReferences": [{"controller": True, "kind": "ReplicaSet",
                                    "name": "langfuse-postgres-abc", "uid": "b" * 36}]},
               "status": {"phase": "Running", "containerStatuses": [{"name": "postgres", "ready": True}]},
               "spec": {"containers": [{"name": "postgres", "image": runtime_image,
                       "volumeMounts": [{"name": "data", "mountPath": "/var/lib/postgresql/data"}]}],
                        "volumes": [{"name": "data", "persistentVolumeClaim":
                                     {"claimName": "wrong-data" if mode == "wrong-pvc" else "langfuse-postgres-data"}}]}}
        print(json.dumps({"kind": "List" if not raw or mode == "generic-cli-list" else "PodList",
            "metadata": {
            "resourceVersion": "" if not raw or mode == "generic-cli-list" else
                               "0" if mode == "zero-list-version" else "12345",
            "continue": "next-page" if mode == "partial-pod-list" else ""},
            "items": [pod, pod] if mode == "two-pods" else [pod]}))
    elif "get" in args and "replicaset" in args:
        print(json.dumps({"metadata": {"uid": "b" * 36,
              "ownerReferences": [{"controller": True, "kind": "Deployment",
                                   "name": "langfuse-postgres",
                                   "uid": "d" * 36 if mode == "wrong-owner" else "c" * 36}]}}))
    elif "exec" in args and "pg_dump" in args:
        Path(os.environ["TEST_DUMPED"]).touch()
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
        assert "source-pvc-uid=" + "e" * 36 in args[args.index("--metadata") + 1]
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
    def run_case(self, mode="good", expected_sha=None, expected_pvc_uid=None,
                 expected_pv_uid=None, local_upload=False):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            for name in ("gh", "git", "kubectl", "aws", "docker"):
                fake = path / name
                fake.write_text(MOCK)
                fake.chmod(0o755)
            receipt_dir = path / "receipts"
            receipt_dir.mkdir(mode=0o700)
            log = path / "commands.jsonl"
            sha = "a" * 40
            env = os.environ | {
                "PATH": f"{path}:{os.environ['PATH']}",
                "GITHUB_ACTIONS": "true",
                "GITHUB_REPOSITORY": "Stuhlmuller/homelab",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_SHA": sha,
                "EXPECTED_SHA": expected_sha or sha,
                "EXPECTED_PVC_UID": expected_pvc_uid or "e" * 36,
                "EXPECTED_PV_UID": expected_pv_uid or "1" * 36,
                "GITHUB_RUN_ID": "123",
                "GITHUB_RUN_ATTEMPT": "1",
                "RUNNER_TEMP": temp,
                "TEST_IMAGE": IMAGE,
                "TEST_MODE": mode,
                "TEST_LOG": str(log),
                "TEST_DUMPED": str(path / "dumped"),
                "TEST_PODS_PATH": PODS_PATH,
                "TEST_ROOT": str(ROOT),
            }
            command = ["bash", str(SCRIPT)]
            if local_upload:
                env.pop("GITHUB_ACTIONS")
                command += ["--local-upload", "--expected-sha", expected_sha or sha,
                            "--expected-pvc-uid", expected_pvc_uid or "e" * 36,
                            "--expected-pv-uid", expected_pv_uid or "1" * 36,
                            "--receipt-dir", str(receipt_dir)]
            result = subprocess.run(command, cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=30)
            commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            receipts = list(receipt_dir.glob("langfuse-checkpoint-pending.*")) if local_upload else []
            receipt = receipts[0] if receipts else path / "langfuse-checkpoint-receipt"
            return result, commands, receipt.read_text() if receipt.exists() else ""

    def test_exact_current_main_restores_downloaded_version_without_network(self):
        result, commands, receipt = self.run_case()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("version=version-1", receipt)
        self.assertIn("tables=8", receipt)
        self.assertIn("pvc_uid=" + "e" * 36, receipt)
        self.assertIn("pv=pvc-" + "e" * 36 + " pv_uid=" + "1" * 36, receipt)
        pod_reads = [args for name, args in commands if name == "kubectl" and
                     ("--raw" in args or "pods" in args and "get" in args)]
        self.assertEqual(pod_reads, [["get", "--raw", PODS_PATH]] * 2)
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

    def test_missing_pv_read_right_prevents_dump_and_upload(self):
        result, commands, receipt = self.run_case("deny-pv")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any("pg_dump" in args or "put-object" in args for _, args in commands))

    def test_missing_pod_list_right_prevents_dump_and_upload(self):
        result, commands, receipt = self.run_case("deny-pod-list")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any("pg_dump" in args or "put-object" in args for _, args in commands))

    def test_wrong_pv_claim_uid_prevents_dump_and_upload(self):
        result, commands, receipt = self.run_case("wrong-pv-owner")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any("pg_dump" in args or "put-object" in args for _, args in commands))

    def test_wrong_nfs_export_prevents_dump_and_upload(self):
        result, commands, receipt = self.run_case("wrong-nfs-path")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any("pg_dump" in args or "put-object" in args for _, args in commands))

    def test_wrong_pv_name_or_deleting_binding_prevents_dump_and_upload(self):
        for mode in ("wrong-pv-name", "pvc-deleting", "pv-deleting"):
            with self.subTest(mode=mode):
                result, commands, receipt = self.run_case(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(receipt, "")
                self.assertFalse(any("pg_dump" in args or "put-object" in args for _, args in commands))

    def test_wrong_expected_source_identity_prevents_dump_and_upload(self):
        for expected in ({"expected_pvc_uid": "3" * 36}, {"expected_pv_uid": "4" * 36}):
            with self.subTest(expected=expected):
                result, commands, receipt = self.run_case(**expected)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(receipt, "")
                self.assertFalse(any("pg_dump" in args or "put-object" in args for _, args in commands))

    def test_replaced_claim_after_dump_prevents_upload(self):
        result, commands, receipt = self.run_case("claim-replaced")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertTrue(any("pg_dump" in args for _, args in commands))
        self.assertFalse(any("put-object" in args for _, args in commands))

    def test_partial_unversioned_or_generic_cli_list_prevents_dump_and_upload(self):
        for mode in ("partial-pod-list", "zero-list-version", "generic-cli-list"):
            with self.subTest(mode=mode):
                result, commands, receipt = self.run_case(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(receipt, "")
                self.assertFalse(any("pg_dump" in args or "put-object" in args for _, args in commands))

    def test_wrong_data_claim_prevents_dump_and_upload(self):
        result, commands, receipt = self.run_case("wrong-pvc")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any("pg_dump" in args or "put-object" in args for _, args in commands))

    def test_upstream_runtime_prevents_dump_and_upload(self):
        result, commands, receipt = self.run_case("upstream-pod")
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

    def test_local_upload_verifies_readback_without_restoring(self):
        result, commands, receipt = self.run_case(local_upload=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Pending receipt: ", result.stdout)
        self.assertIn("Pending Langfuse PostgreSQL restore:", receipt)
        self.assertNotIn("Verified Langfuse PostgreSQL checkpoint:", receipt)
        self.assertRegex(receipt, r"key=langfuse/postgresql/[0-9a-f]{40}/[1-9][0-9]*/1/langfuse.dump")
        self.assertFalse(any(name == "docker" for name, _ in commands))
        self.assertTrue(all("--profile" in args and args[args.index("--profile") + 1] == "default"
                            for name, args in commands if name == "aws"))
        self.assertFalse(any(name in ("pg_restore", "pg_ctl", "postgres")
                             for name, _ in commands))

    def test_local_upload_rejects_stale_or_dirty_main_before_credentials(self):
        for mode in ("stale-local", "dirty-checkout", "main-advanced"):
            with self.subTest(mode=mode):
                result, commands, receipt = self.run_case(mode, local_upload=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(receipt, "")
                self.assertFalse(any(name in ("aws", "docker", "pg_restore") for name, _ in commands))

    def test_local_upload_rejects_insecure_kubeconfig(self):
        for mode in ("insecure-kubeconfig",):
            with self.subTest(mode=mode):
                result, commands, receipt = self.run_case(mode, local_upload=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(receipt, "")
                self.assertFalse(any("put-object" in args for _, args in commands))

    def test_local_upload_corrupt_readback_has_no_pending_receipt(self):
        result, commands, receipt = self.run_case("corrupt-readback", local_upload=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any(name in ("docker", "pg_restore") for name, _ in commands))

    def test_local_upload_rechecks_main_before_put_and_pending_receipt(self):
        result, commands, receipt = self.run_case("main-advanced-after-dump", local_upload=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any("put-object" in args for _, args in commands))
        result, commands, receipt = self.run_case("main-advanced-after-upload", local_upload=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertTrue(any("put-object" in args for _, args in commands))


if __name__ == "__main__":
    unittest.main()
