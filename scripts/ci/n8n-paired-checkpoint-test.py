#!/usr/bin/env python3
"""Fail-closed command boundary checks for the inactive protected checkpoint."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/n8n-paired-checkpoint.sh"
UUID = "1" * 8 + "-" + "1" * 4 + "-" + "1" * 4 + "-" + "1" * 4 + "-" + "1" * 12

MOCK = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
mode = os.environ["TEST_MODE"]
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps([name, args]) + "\n")
if name == "git":
    print(os.environ["GITHUB_SHA"])
elif name == "gh":
    print("f" * 40 if mode == "main-advanced" else os.environ["GITHUB_SHA"])
elif name == "rg":
    raise SystemExit(1 if any("migration-v1.values.yaml" in arg or "checkpoint-reader.job.yaml" in arg
                              for arg in args) else 0)
elif name == "aws":
    if "get-caller-identity" in args:
        print("716182248480")
    elif "get-bucket-versioning" in args:
        print("Enabled")
    elif "get-bucket-encryption" in args:
        print("aws:kms")
    else:
        raise SystemExit("unexpected aws command")
elif name == "kubectl":
    if args[:2] == ["auth", "can-i"]:
        print("no" if mode == "deny-job-create" and args[2:4] == ["create", "jobs"] else "yes")
    elif "application" in args and "get" in args:
        print(json.dumps({"status": {"sync": {"status": "OutOfSync" if mode == "fence-unsynced" else "Synced",
            "revisions": ["4.4.0", os.environ["GITHUB_SHA"], os.environ["GITHUB_SHA"]]},
            "health": {"status": "Healthy"}}}))
    elif "deployment" in args and "get" in args:
        print(json.dumps({"metadata": {"generation": 1}, "spec": {"replicas": 1},
                          "status": {"observedGeneration": 1, "replicas": 1, "readyReplicas": 1}}))
    else:
        raise SystemExit("unexpected kubectl command")
elif name == "yq":
    print(os.environ["TEST_IMAGE"] if "statefulset.yaml" in args[-1] else os.environ["TEST_READER_IMAGE"])
else:
    raise SystemExit("unknown mock binary")
'''

FULL_MOCK = r'''#!/usr/bin/env python3
import base64, hashlib, io, json, os, sys, tarfile
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path(os.environ["TEST_ROOT"])
created = root / "job-created"
policy = root / "policy-created"
image = os.environ["TEST_IMAGE"]
reader_image = os.environ["TEST_READER_IMAGE"]
sha = os.environ["GITHUB_SHA"]
u = os.environ["TEST_UUID"]
pg_u = "2" * 8 + "-" + "2" * 4 + "-" + "2" * 4 + "-" + "2" * 4 + "-" + "2" * 12
pg_pv_u = "4" * 8 + "-" + "4" * 4 + "-" + "4" * 4 + "-" + "4" * 4 + "-" + "4" * 12
reader_u = "5" * 8 + "-" + "5" * 4 + "-" + "5" * 4 + "-" + "5" * 4 + "-" + "5" * 12
job_u = "6" * 8 + "-" + "6" * 4 + "-" + "6" * 4 + "-" + "6" * 4 + "-" + "6" * 12
pg_pod_u = "7" * 8 + "-" + "7" * 4 + "-" + "7" * 4 + "-" + "7" * 4 + "-" + "7" * 12
st_u = "8" * 8 + "-" + "8" * 4 + "-" + "8" * 4 + "-" + "8" * 4 + "-" + "8" * 12
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps([name, args]) + "\n")
if name == "git":
    print(sha)
elif name == "gh":
    print(sha)
elif name == "rg":
    raise SystemExit(1 if any("migration-v1.values.yaml" in a or "checkpoint-reader.job.yaml" in a
                              for a in args) else 0)
elif name == "yq":
    print(image if "statefulset.yaml" in args[-1] else reader_image)
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
        key = args[args.index("--key") + 1]
        source = Path(args[args.index("--body") + 1])
        assert args[args.index("--if-none-match") + 1] == "*"
        assert args[args.index("--server-side-encryption") + 1] == "aws:kms"
        assert key.startswith("n8n/paired/" + sha + "/123/1/")
        body = source.read_bytes()
        (root / key.rsplit("/", 1)[-1]).write_bytes(body)
        print(json.dumps({"VersionId": "v-" + key.rsplit("/", 1)[-1]}))
    elif "head-object" in args or "get-object" in args:
        key = args[args.index("--key") + 1]
        version = "v-" + key.rsplit("/", 1)[-1]
        assert args[args.index("--version-id") + 1] == version
        body = (root / key.rsplit("/", 1)[-1]).read_bytes()
        metadata = {"VersionId": version, "ChecksumSHA256":
            base64.b64encode(hashlib.sha256(body).digest()).decode(),
            "ContentLength": len(body), "ServerSideEncryption": "aws:kms"}
        if "get-object" in args:
            Path(args[-1]).write_bytes(body)
        print(json.dumps(metadata))
    else:
        raise SystemExit("unexpected aws command " + repr(args))
elif name == "kubectl":
    if args[:2] == ["auth", "can-i"]:
        print("yes")
    elif "application" in args and "get" in args:
        print(json.dumps({"status": {"sync": {"status": "Synced", "revisions": ["4.4.0", sha, sha]},
            "health": {"status": "Healthy"}}}))
    elif "deployment" in args and "get" in args:
        print(json.dumps({"metadata": {"generation": 1}, "spec": {"replicas": 0},
            "status": {"observedGeneration": 1, "replicas": 0, "readyReplicas": 0}}))
    elif args[:2] == ["get", "--raw"]:
        raw = args[2]
        reader = {"metadata": {"name": "n8n-checkpoint-reader-abcde", "uid": reader_u,
            "labels": {"app.kubernetes.io/name": "n8n-checkpoint-reader"},
            "ownerReferences": [{"controller": True, "kind": "Job", "name": "n8n-checkpoint-reader", "uid": job_u}]},
            "status": {"phase": "Running", "containerStatuses": [{"name": "reader", "ready": True}]},
            "spec": {"automountServiceAccountToken": False,
                "containers": [{"name": "reader", "image": reader_image,
                    "volumeMounts": [{"name": "source", "mountPath": "/source", "readOnly": True}]}],
                "volumes": [{"name": "source", "persistentVolumeClaim":
                    {"claimName": "n8n", "readOnly": True}}]}}
        assert raw in ("/api/v1/namespaces/automation/pods?limit=500",
                       "/api/v1/namespaces/automation/pods?labelSelector=job-name%3Dn8n-checkpoint-reader")
        items = [reader] if created.exists() else []
        print(json.dumps({"kind": "PodList", "metadata": {"resourceVersion": "12345", "continue": ""},
            "items": items}))
    elif "jobs,cronjobs" in args:
        print(json.dumps({"items": []}))
    elif "pvc" in args and "get" in args:
        claim = args[args.index("pvc") + 1]
        uid = u if claim == "n8n" else pg_u
        print(json.dumps({"kind": "PersistentVolumeClaim",
            "metadata": {"namespace": "automation", "name": claim, "uid": uid},
            "status": {"phase": "Bound"},
            "spec": {"storageClassName": "nfs-default", "accessModes": ["ReadWriteOnce"],
                "volumeName": "pvc-" + uid}}))
    elif "pv" in args and "get" in args:
        pv = args[args.index("pv") + 1]
        uid = pv.removeprefix("pvc-")
        claim = "n8n" if uid == u else "data-n8n-postgres-0"
        print(json.dumps({"kind": "PersistentVolume", "metadata": {"name": pv,
            "uid": "3" * 8 + "-" + "3" * 4 + "-" + "3" * 4 + "-" + "3" * 4 + "-" + "3" * 12 if uid == u else pg_pv_u},
            "status": {"phase": "Bound"}, "spec": {"storageClassName": "nfs-default",
                "persistentVolumeReclaimPolicy": "Retain", "nfs": {"server": "10.1.0.2",
                    "path": "/homelab/automation-" + claim + "-pvc-" + uid},
                "claimRef": {"namespace": "automation", "name": claim, "uid": uid}}}))
    elif "statefulset" in args and "get" in args:
        print(json.dumps({"metadata": {"uid": st_u, "generation": 1},
            "spec": {"replicas": 1, "template": {"spec": {"containers":
                [{"name": "postgres", "image": image}]}}, "volumeClaimTemplates": [{"metadata": {"name": "data"}}]},
            "status": {"readyReplicas": 1, "updatedReplicas": 1, "observedGeneration": 1}}))
    elif "pod" in args and "get" in args:
        print(json.dumps({"metadata": {"uid": pg_pod_u, "ownerReferences":
            [{"controller": True, "kind": "StatefulSet", "name": "n8n-postgres", "uid": st_u}]},
            "status": {"phase": "Running", "containerStatuses": [{"name": "postgres", "ready": True}]},
            "spec": {"containers": [{"name": "postgres", "image": image, "volumeMounts":
                [{"name": "data", "mountPath": "/var/lib/postgresql/data"}]}],
                "volumes": [{"name": "data", "persistentVolumeClaim":
                    {"claimName": "data-n8n-postgres-0"}}]}}))
    elif "job" in args and "get" in args:
        print(json.dumps({"metadata": {"uid": job_u}, "spec":
            {"backoffLimit": 0, "activeDeadlineSeconds": 3600}, "status": {"active": 1}}))
    elif "networkpolicy" in args and "get" in args:
        assert policy.exists()
        print(json.dumps({"spec": {"podSelector": {"matchLabels":
            {"app.kubernetes.io/name": "n8n-checkpoint-reader"}},
            "policyTypes": ["Ingress", "Egress"]}}))
    elif "create" in args:
        if "networkpolicy" in args[args.index("-f") + 1]:
            assert not policy.exists()
            policy.touch()
            print("networkpolicy.networking.k8s.io/n8n-checkpoint-reader")
        else:
            assert policy.exists() and not created.exists()
            created.touch()
            print("job.batch/n8n-checkpoint-reader")
    elif "delete" in args:
        if "networkpolicy" in args[args.index("-f") + 1]:
            assert not created.exists()
            policy.unlink()
        else:
            created.unlink()
    elif "exec" in args:
        if "psql" in args:
            print("12345" if "pg_database_size" in args[-1] else "1")
        elif "pg_dump" in args:
            sys.stdout.buffer.write(b"PGDMPtest-fixture")
        elif "tar" in args:
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode="w") as archive:
                body = b'{"encryptionKey":"private-test-key"}'
                entry = tarfile.TarInfo("./config")
                entry.size = len(body)
                archive.addfile(entry, io.BytesIO(body))
            sys.stdout.buffer.write(output.getvalue())
        else:
            raise SystemExit("unexpected exec " + repr(args))
    else:
        raise SystemExit("unexpected kubectl command " + repr(args))
elif name == "docker":
    if args[:2] == ["volume", "create"]:
        print("volume-created")
    elif args[0] == "run":
        assert args[args.index("--network") + 1] == "none"
        print("container-1")
    elif args[0] == "exec" and "psql" in args:
        print("4")
    elif args[0] in ("exec", "rm", "volume"):
        pass
    else:
        raise SystemExit("unexpected docker command " + repr(args))
else:
    raise SystemExit("unknown mock binary")
'''


class CheckpointBoundaryTests(unittest.TestCase):
    def run_case(self, mode="deployment-active", **overrides):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            for name in ("git", "gh", "rg", "aws", "kubectl", "yq", "docker"):
                fake = path / name
                fake.write_text(FULL_MOCK if mode == "good" else MOCK)
                fake.chmod(0o755)
            log = path / "commands.jsonl"
            sha = "a" * 40
            env = os.environ | {
                "PATH": f"{path}:{os.environ['PATH']}",
                "GITHUB_ACTIONS": "true",
                "GITHUB_REPOSITORY": "Stuhlmuller/homelab",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_SHA": sha,
                "EXPECTED_SHA": sha,
                "EXPECTED_N8N_PVC_UID": UUID,
                "EXPECTED_N8N_PV_UID": UUID,
                "EXPECTED_PG_PVC_UID": UUID,
                "EXPECTED_PG_PV_UID": UUID,
                "GITHUB_RUN_ID": "123",
                "GITHUB_RUN_ATTEMPT": "1",
                "TEST_MODE": mode,
                "TEST_LOG": str(log),
                "TEST_IMAGE": "harbor.stinkyboi.com/mirror/docker.io/library/postgres:test@sha256:" + "a" * 64,
                "TEST_READER_IMAGE": "harbor.stinkyboi.com/mirror/docker.io/library/busybox:1.38.0@sha256:fd7dc98638c8e305f4dc34e979f1c0fdfdcaeb0fbf8fcff77ae834b6da3d7e6e",
                "RUNNER_TEMP": temporary,
                "TEST_ROOT": temporary,
                "TEST_UUID": UUID,
            } | overrides
            if mode == "good":
                env["EXPECTED_PG_PVC_UID"] = "2" * 8 + "-" + "2" * 4 + "-" + "2" * 4 + "-" + "2" * 4 + "-" + "2" * 12
                env["EXPECTED_N8N_PV_UID"] = "3" * 8 + "-" + "3" * 4 + "-" + "3" * 4 + "-" + "3" * 4 + "-" + "3" * 12
                env["EXPECTED_PG_PV_UID"] = "4" * 8 + "-" + "4" * 4 + "-" + "4" * 4 + "-" + "4" * 4 + "-" + "4" * 12
            result = subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=30)
            commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            receipt = path / "n8n-paired-checkpoint-receipt"
            return result, commands, receipt.read_text() if receipt.exists() else ""

    def assert_no_mutation(self, commands):
        self.assertFalse(any(name == "kubectl" and args[:2] != ["auth", "can-i"] and
                             any(arg in args for arg in ("create", "delete", "exec"))
                             or name == "aws" and any(arg in args for arg in ("put-object", "get-object"))
                             for name, args in commands))

    def test_stale_dispatch_stops_before_any_tool(self):
        result, commands, _ = self.run_case(EXPECTED_SHA="b" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(commands, [])

    def test_invalid_source_uid_stops_before_any_tool(self):
        result, commands, _ = self.run_case(EXPECTED_N8N_PVC_UID="wrong")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(commands, [])

    def test_advanced_main_stops_before_aws_or_kubernetes(self):
        result, commands, _ = self.run_case("main-advanced")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([name for name, _ in commands], ["git", "gh"])

    def test_missing_job_create_right_stops_before_kubernetes_mutation(self):
        result, commands, _ = self.run_case("deny-job-create")
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_mutation(commands)

    def test_unsynced_fence_stops_before_job_creation(self):
        result, commands, _ = self.run_case("fence-unsynced")
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_mutation(commands)

    def test_nonzero_deployment_stops_before_job_creation(self):
        result, commands, _ = self.run_case()
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_mutation(commands)

    def test_success_publishes_only_after_pair_readback_and_offline_restore(self):
        result, commands, receipt = self.run_case("good")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("manifest=n8n/paired/" + "a" * 40 + "/123/1/manifest.json", receipt)
        self.assertIn("tables=4 files=1", receipt)
        self.assertNotIn("private-test-key", result.stdout + result.stderr + receipt)
        puts = [args for name, args in commands if name == "aws" and "put-object" in args]
        self.assertEqual([args[args.index("--key") + 1].rsplit("/", 1)[-1] for args in puts],
                         ["n8n.dump", "n8n.tar", "manifest.json"])
        self.assertTrue(any(name == "docker" and args[0] == "run" and "--network" in args
                            for name, args in commands))
        self.assertTrue(any(name == "kubectl" and "delete" in args for name, args in commands))


if __name__ == "__main__":
    unittest.main()
