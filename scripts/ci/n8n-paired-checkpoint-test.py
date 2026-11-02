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
import base64, hashlib, io, json, os, sys, tarfile
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path(os.environ["TEST_ROOT"])
job_record = root / "job-record.json"
policy_record = root / "policy-record.json"
linger_record = root / "reader-lingers"
resource_name = "n8n-checkpoint-reader-123-1"
image = os.environ["TEST_IMAGE"]
reader_image = os.environ["TEST_READER_IMAGE"]
sha = os.environ["GITHUB_SHA"]
mode = os.environ["TEST_MODE"]
u = os.environ["TEST_UUID"]
pg_u = "2" * 8 + "-" + "2" * 4 + "-" + "2" * 4 + "-" + "2" * 4 + "-" + "2" * 12
pg_pv_u = "4" * 8 + "-" + "4" * 4 + "-" + "4" * 4 + "-" + "4" * 4 + "-" + "4" * 12
reader_u = "5" * 8 + "-" + "5" * 4 + "-" + "5" * 4 + "-" + "5" * 4 + "-" + "5" * 12
job_u = "6" * 8 + "-" + "6" * 4 + "-" + "6" * 4 + "-" + "6" * 4 + "-" + "6" * 12
pg_pod_u = "7" * 8 + "-" + "7" * 4 + "-" + "7" * 4 + "-" + "7" * 4 + "-" + "7" * 12
st_u = "8" * 8 + "-" + "8" * 4 + "-" + "8" * 4 + "-" + "8" * 4 + "-" + "8" * 12
def record(binary, arguments):
    with open(os.environ["TEST_LOG"], "a") as log:
        log.write(json.dumps([binary, arguments]) + "\n")
record(name, args)
if name == "timeout":
    assert args[:2] in (["--signal=TERM", "--kill-after=10s"],
                        ["--signal=TERM", "--kill-after=30s"])
    assert args[2] in ("45s", "2m", "15m")
    if (mode == "pg-dump-timeout" and "pg_dump" in args) or (mode == "pvc-tar-timeout" and "tar" in args):
        raise SystemExit(124)
    if mode == "job-absent-reader-lingers" and "pg_dump" in args:
        job_record.unlink()
        linger_record.touch()
        raise SystemExit(124)
    if mode == "job-delete-timeout" and "delete" in args and any(a.endswith("/job.json") for a in args):
        raise SystemExit(124)
    assert Path(args[3]).name == "kubectl"
    name = "kubectl"
    args = args[4:]
    if args and args[0].startswith("--request-timeout="):
        args = args[1:]
    record(name, args)
if name == "git":
    print(sha)
elif name == "gh":
    print("f" * 40 if mode == "main-advanced" else sha)
    if mode == "main-read-partial-error":
        raise SystemExit(1)
elif name == "rg":
    if any("targetRevision" in a for a in args):
        print('        targetRevision = "4.4.0"\n        targetRevision = local.shared.target_revision\n        targetRevision = local.shared.target_revision')
    elif any("valueFiles" in a for a in args):
        print('          valueFiles  = ["$values/clusters/homelab/apps/n8n/values.yaml", "$values/clusters/homelab/apps/n8n/maintenance-fence.values.yaml"]')
    elif mode == "source-rg-error" and "checkpoint-reader.job.yaml" in args:
        raise SystemExit(2)
    else:
        raise SystemExit(1)
elif name == "yq":
    if args[0] == "-r":
        print(image if "statefulset.yaml" in args[-1] else reader_image)
    elif "networkpolicy" in args[-1]:
        print(json.dumps({"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": {"name": "n8n-checkpoint-reader", "namespace": "automation"},
            "spec": {"podSelector": {"matchLabels": {"app.kubernetes.io/name": "n8n-checkpoint-reader"}},
                     "policyTypes": ["Ingress", "Egress"]}}))
    else:
        print(json.dumps({"apiVersion": "batch/v1", "kind": "Job",
            "metadata": {"name": "n8n-checkpoint-reader", "namespace": "automation", "labels": {}},
            "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 3600,
                     "template": {"metadata": {"labels": {"app.kubernetes.io/name": "n8n-checkpoint-reader"}}}}}))
elif name == "aws":
    if "get-caller-identity" in args:
        print("716182248480")
    elif "get-bucket-versioning" in args:
        print("Enabled")
    elif "get-bucket-encryption" in args:
        print("aws:kms")
        if mode == "encryption-read-partial-error":
            raise SystemExit(1)
    elif "list-object-versions" in args:
        print(json.dumps({"Versions": [], "DeleteMarkers": []}))
        if mode == "s3-list-partial-error":
            raise SystemExit(1)
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
        if (mode == "s3-head-partial-error" and "head-object" in args) or \
           (mode == "s3-get-partial-error" and "get-object" in args):
            raise SystemExit(1)
    else:
        raise SystemExit("unexpected aws command " + repr(args))
elif name == "kubectl":
    if args[:2] == ["auth", "can-i"]:
        print("no" if mode == "deny-job-create" and args[2:4] == ["create", "jobs"] else "yes")
        if mode == "auth-partial-error" and args[2:4] == ["create", "jobs"]:
            raise SystemExit(1)
    elif "application" in args and "get" in args:
        print(json.dumps({"status": {"sync": {"status": "OutOfSync" if mode == "fence-unsynced" else "Synced", "revisions": ["4.4.0", sha, sha]},
            "health": {"status": "Healthy"}}}))
    elif "deployment" in args and "get" in args:
        replicas = 1 if mode == "deployment-active" else 0
        print(json.dumps({"metadata": {"generation": 1}, "spec": {"replicas": replicas},
            "status": {"observedGeneration": 1, "replicas": replicas, "readyReplicas": replicas}}))
    elif args[:2] == ["get", "--raw"]:
        raw = args[2]
        owner = json.loads(job_record.read_text())["metadata"]["labels"]["homelab.stuhlmuller.dev/checkpoint-owner"] if job_record.exists() else ""
        reader = {"metadata": {"name": resource_name + "-abcde", "uid": reader_u,
            "labels": {"app.kubernetes.io/name": "n8n-checkpoint-reader",
                       "homelab.stuhlmuller.dev/checkpoint-owner": owner},
            "ownerReferences": [{"controller": True, "kind": "Job", "name": resource_name, "uid": job_u}]},
            "status": {"phase": "Running", "containerStatuses": [{"name": "reader", "ready": True}]},
            "spec": {"automountServiceAccountToken": False,
                "containers": [{"name": "reader", "image": reader_image,
                    "volumeMounts": [{"name": "source", "mountPath": "/source", "readOnly": True}]}],
                "volumes": [{"name": "source", "persistentVolumeClaim":
                    {"claimName": "n8n", "readOnly": True}}]}}
        assert raw in ("/api/v1/namespaces/automation/pods?limit=500",
                       "/api/v1/namespaces/automation/pods?labelSelector=batch.kubernetes.io%2Fjob-name%3D" + resource_name)
        items = [reader] if job_record.exists() else []
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
        if mode == "pv-binding-partial-error" and uid == u:
            calls = root / "n8n-pv-calls"
            count = int(calls.read_text()) + 1 if calls.exists() else 1
            calls.write_text(str(count))
            if count == 2:
                raise SystemExit(1)
    elif "statefulset" in args and "get" in args:
        print(json.dumps({"metadata": {"uid": st_u, "generation": 1},
            "spec": {"replicas": 1, "template": {"spec": {"containers":
                [{"name": "postgres", "image": image}]}}, "volumeClaimTemplates": [{"metadata": {"name": "data"}}]},
            "status": {"readyReplicas": 1, "updatedReplicas": 1, "observedGeneration": 1}}))
        if mode == "pg-state-partial-error":
            calls = root / "statefulset-calls"
            count = int(calls.read_text()) + 1 if calls.exists() else 1
            calls.write_text(str(count))
            if count == 2:
                raise SystemExit(1)
    elif "pods" in args and "get" in args:
        assert args[args.index("-l") + 1].startswith("homelab.stuhlmuller.dev/checkpoint-owner=")
        assert "--chunk-size=0" in args
        print(json.dumps({"kind": "PodList", "metadata": {"resourceVersion": "12345", "continue": ""},
            "items": [{"metadata": {"uid": reader_u}}] if linger_record.exists() else []}))
    elif "pod" in args and "get" in args:
        print(json.dumps({"metadata": {"uid": pg_pod_u, "ownerReferences":
            [{"controller": True, "kind": "StatefulSet", "name": "n8n-postgres", "uid": st_u}]},
            "status": {"phase": "Running", "containerStatuses": [{"name": "postgres", "ready": True}]},
            "spec": {"containers": [{"name": "postgres", "image": image, "volumeMounts":
                [{"name": "data", "mountPath": "/var/lib/postgresql/data"}]}],
                "volumes": [{"name": "data", "persistentVolumeClaim":
                    {"claimName": "data-n8n-postgres-0"}}]}}))
    elif "job" in args and "get" in args:
        if job_record.exists():
            print(job_record.read_text())
        elif "--ignore-not-found" not in args:
            raise SystemExit(1)
    elif "networkpolicy" in args and "get" in args:
        if policy_record.exists():
            print(policy_record.read_text())
        elif "--ignore-not-found" not in args:
            raise SystemExit(1)
    elif "create" in args:
        source = Path(args[args.index("-f") + 1])
        obj = json.loads(source.read_text())
        assert obj["metadata"]["name"] == resource_name
        if obj["kind"] == "NetworkPolicy":
            assert not policy_record.exists()
            obj["metadata"]["uid"] = "9" * 8 + "-" + "9" * 4 + "-" + "9" * 4 + "-" + "9" * 4 + "-" + "9" * 12
            policy_record.write_text(json.dumps(obj))
            if mode == "policy-create-timeout":
                raise SystemExit(1)
            print("networkpolicy.networking.k8s.io/" + resource_name)
        else:
            assert policy_record.exists() and not job_record.exists()
            obj["metadata"]["uid"] = job_u
            obj["status"] = {"active": 1}
            if mode == "job-owner-mismatch":
                obj["metadata"]["labels"]["homelab.stuhlmuller.dev/checkpoint-owner"] = "foreign"
            job_record.write_text(json.dumps(obj))
            if mode in ("job-create-timeout", "job-owner-mismatch"):
                raise SystemExit(1)
            print("job.batch/" + resource_name)
    elif "delete" in args:
        source = Path(args[args.index("-f") + 1])
        obj = json.loads(source.read_text())
        if obj["kind"] == "NetworkPolicy":
            assert not job_record.exists()
            policy_record.unlink()
        else:
            assert "--cascade=foreground" in args
            if mode == "job-delete-stuck":
                raise SystemExit(1)
            job_record.unlink()
            if mode == "reader-pod-lingers":
                linger_record.touch()
    elif "exec" in args:
        if "psql" in args:
            print("12345" if "pg_database_size" in args[-1] else "1")
            if mode == "pg-liveness-partial-error" and args[-1] == "SELECT 1":
                raise SystemExit(1)
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
    elif args[0] == "rm" and mode == "docker-rm-stuck":
        raise SystemExit(1)
    elif args[0] in ("exec", "rm", "volume"):
        pass
    else:
        raise SystemExit("unexpected docker command " + repr(args))
elif name == "sleep":
    pass
elif name == "sha256sum":
    source = Path(args[0])
    print(hashlib.sha256(source.read_bytes()).hexdigest() + "  " + str(source))
    if mode == "checksum-partial-error" and source.name == "retrieved.dump":
        raise SystemExit(1)
else:
    raise SystemExit("unknown mock binary")
'''


class CheckpointBoundaryTests(unittest.TestCase):
    def run_case(self, mode="deployment-active", **overrides):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            for name in ("git", "gh", "rg", "aws", "kubectl", "yq", "docker", "timeout", "sleep", "sha256sum"):
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
            if mode in ("good", "policy-create-timeout", "job-create-timeout",
                        "job-delete-stuck", "job-owner-mismatch", "docker-rm-stuck",
                        "pg-dump-timeout", "pvc-tar-timeout", "job-delete-timeout",
                        "reader-pod-lingers", "job-absent-reader-lingers",
                        "pg-liveness-partial-error", "pg-state-partial-error",
                        "pv-binding-partial-error", "checksum-partial-error",
                        "s3-list-partial-error", "s3-head-partial-error",
                        "s3-get-partial-error"):
                env["EXPECTED_PG_PVC_UID"] = "2" * 8 + "-" + "2" * 4 + "-" + "2" * 4 + "-" + "2" * 4 + "-" + "2" * 12
                env["EXPECTED_N8N_PV_UID"] = "3" * 8 + "-" + "3" * 4 + "-" + "3" * 4 + "-" + "3" * 4 + "-" + "3" * 12
                env["EXPECTED_PG_PV_UID"] = "4" * 8 + "-" + "4" * 4 + "-" + "4" * 4 + "-" + "4" * 4 + "-" + "4" * 12
            try:
                result = subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=env,
                                        capture_output=True, text=True, timeout=60)
            except subprocess.TimeoutExpired as error:
                recent = log.read_text().splitlines()[-8:] if log.exists() else []
                raise AssertionError(f"checkpoint fixture timed out after {recent}") from error
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

    def test_expected_preflight_output_with_failed_command_stops(self):
        for mode in ("main-read-partial-error", "encryption-read-partial-error",
                     "auth-partial-error"):
            with self.subTest(mode=mode):
                result, commands, receipt = self.run_case(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(receipt, "")
                self.assert_no_mutation(commands)

    def test_failed_negative_source_search_stops_before_kubernetes(self):
        result, commands, receipt = self.run_case("source-rg-error")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assert_no_mutation(commands)

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
        self.assertEqual(result.returncode, 0, result.stderr + repr(commands[-12:]))
        self.assertIn("manifest=n8n/paired/" + "a" * 40 + "/123/1/manifest.json", receipt)
        self.assertIn("tables=4 files=1", receipt)
        self.assertNotIn("private-test-key", result.stdout + result.stderr + receipt)
        puts = [args for name, args in commands if name == "aws" and "put-object" in args]
        self.assertEqual([args[args.index("--key") + 1].rsplit("/", 1)[-1] for args in puts],
                         ["n8n.dump", "n8n.tar", "manifest.json"])
        self.assertTrue(any(name == "docker" and args[0] == "run" and "--network" in args
                            for name, args in commands))
        self.assertTrue(any(name == "docker" and args[:2] == ["exec", "container-1"] and
                            "pg_restore" in args and args[args.index("-U") + 1] == "n8n"
                            for name, args in commands))
        self.assertTrue(any(name == "docker" and args[:2] == ["exec", "container-1"] and
                            "SELECT 1 FROM public.workflow_entity LIMIT 0" in args and
                            args[args.index("-U") + 1] == "n8n" for name, args in commands))
        self.assertTrue(any(name == "kubectl" and "delete" in args for name, args in commands))

    def test_source_check_output_with_failed_command_blocks_publication(self):
        for mode in ("pg-liveness-partial-error", "pg-state-partial-error",
                     "pv-binding-partial-error"):
            with self.subTest(mode=mode):
                result, commands, receipt = self.run_case(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(receipt, "")
                self.assertFalse(any(name == "aws" and "put-object" in args for name, args in commands))

    def test_s3_success_output_with_failed_command_blocks_receipt(self):
        for mode in ("s3-list-partial-error", "s3-head-partial-error",
                     "s3-get-partial-error", "checksum-partial-error"):
            with self.subTest(mode=mode):
                result, commands, receipt = self.run_case(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(receipt, "")
                puts = [args for name, args in commands if name == "aws" and "put-object" in args]
                self.assertEqual(len(puts), 0 if mode == "s3-list-partial-error" else 1)

    def test_committed_create_with_lost_response_reconciles_and_cleans(self):
        for mode in ("policy-create-timeout", "job-create-timeout"):
            with self.subTest(mode=mode):
                result, commands, receipt = self.run_case(mode)
                self.assertEqual(result.returncode, 0, result.stderr + repr(commands[-12:]))
                self.assertIn("Verified n8n paired checkpoint", receipt)
                deletions = [args for name, args in commands if name == "kubectl" and
                             args[:2] != ["auth", "can-i"] and "delete" in args]
                self.assertEqual(len(deletions), 2)

    def test_failed_reader_cleanup_blocks_receipt(self):
        result, commands, receipt = self.run_case("job-delete-stuck")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any(name == "aws" and "put-object" in args for name, args in commands))
        self.assertTrue(any(name == "kubectl" and args[:2] != ["auth", "can-i"] and
                            "delete" in args for name, args in commands))

    def test_ambiguous_foreign_job_is_never_deleted(self):
        result, commands, receipt = self.run_case("job-owner-mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any(name == "kubectl" and args[:2] != ["auth", "can-i"] and
                             "delete" in args for name, args in commands))
        self.assertFalse(any(name == "aws" and "put-object" in args for name, args in commands))

    def test_failed_offline_restore_cleanup_blocks_receipt(self):
        result, commands, receipt = self.run_case("docker-rm-stuck")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertEqual(sum(name == "aws" and "put-object" in args for name, args in commands), 3)

    def test_capture_stream_timeout_cleans_reader_without_receipt(self):
        for mode in ("pg-dump-timeout", "pvc-tar-timeout"):
            with self.subTest(mode=mode):
                result, commands, receipt = self.run_case(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(receipt, "")
                self.assertFalse(any(name == "aws" and "put-object" in args for name, args in commands))
                captures = [args for name, args in commands if name == "timeout" and args[2] == "15m"]
                self.assertEqual(len(captures), 1 if mode == "pg-dump-timeout" else 2)
                self.assertEqual([args[:3] for args in captures],
                                 [["--signal=TERM", "--kill-after=30s", "15m"]] * len(captures))
                deletions = [args for name, args in commands if name == "kubectl" and
                             args[:2] != ["auth", "can-i"] and "delete" in args]
                self.assertEqual(len(deletions), 2)

    def test_control_plane_calls_are_bounded_and_cleanup_timeout_blocks_receipt(self):
        result, commands, receipt = self.run_case("job-delete-timeout")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt, "")
        self.assertFalse(any(name == "aws" and "put-object" in args for name, args in commands))
        bounded = [args for name, args in commands if name == "timeout" and args[2] == "45s"]
        self.assertTrue(bounded)
        self.assertTrue(all("--request-timeout=30s" in args for args in bounded))
        deletes = [args for name, args in commands if name == "timeout" and args[2] == "2m" and "delete" in args]
        self.assertTrue(deletes)
        self.assertTrue(all("--request-timeout=60s" in args for args in deletes))

    def test_lingering_reader_pod_keeps_policy_and_blocks_receipt(self):
        for mode in ("reader-pod-lingers", "job-absent-reader-lingers"):
            with self.subTest(mode=mode):
                result, commands, receipt = self.run_case(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(receipt, "")
                self.assertFalse(any(name == "aws" and "put-object" in args for name, args in commands))
                self.assertTrue(any(name == "kubectl" and "get" in args and "pods" in args and
                                    "--chunk-size=0" in args for name, args in commands))
                deletes = [args for name, args in commands if name == "kubectl" and
                           args[:2] != ["auth", "can-i"] and "delete" in args]
                self.assertEqual(len(deletes), 1 if mode == "reader-pod-lingers" else 0)


if __name__ == "__main__":
    unittest.main()
