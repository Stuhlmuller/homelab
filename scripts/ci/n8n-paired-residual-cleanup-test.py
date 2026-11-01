#!/usr/bin/env python3
"""Fail-closed cleanup of a cancelled n8n paired-checkpoint reader."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/n8n-paired-residual-cleanup.sh"
SHA = "a" * 40
NAME = "n8n-checkpoint-reader-123-1"
OWNER = "b" * 32
JOB_UID = "11111111-1111-1111-1111-111111111111"
POLICY_UID = "22222222-2222-2222-2222-222222222222"
POD_UID = "33333333-3333-3333-3333-333333333333"
IMAGE = "harbor.stinkyboi.com/mirror/docker.io/library/busybox:1.38.0@sha256:" + "f" * 64
CONTAINER = {
    "name": "reader", "image": IMAGE, "command": ["/bin/sh", "-ec"],
    "args": ["test -s /source/config\nexec sleep 3300\n"],
    "securityContext": {"allowPrivilegeEscalation": False},
    "volumeMounts": [{"name": "source", "mountPath": "/source", "readOnly": True}],
}
VOLUME = {"name": "source", "persistentVolumeClaim": {"claimName": "n8n", "readOnly": True}}
LABEL = "homelab.stuhlmuller.dev/checkpoint-owner"


def initial_state():
    return {
        "job": {
            "apiVersion": "batch/v1", "kind": "Job",
            "metadata": {"name": NAME, "namespace": "automation", "uid": JOB_UID,
                         "resourceVersion": "11", "labels": {
                             "app.kubernetes.io/name": "n8n-checkpoint-reader", LABEL: OWNER}},
            "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 3600,
                     "template": {"metadata": {"labels": {
                         "app.kubernetes.io/name": "n8n-checkpoint-reader", LABEL: OWNER},
                         "annotations": {"sidecar.istio.io/inject": "false"}},
                         "spec": {"automountServiceAccountToken": False,
                                  "restartPolicy": "Never", "containers": [CONTAINER],
                                  "volumes": [VOLUME]}}},
        },
        "policy": {
            "apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": {"name": NAME, "namespace": "automation", "uid": POLICY_UID,
                         "resourceVersion": "22", "labels": {LABEL: OWNER}},
            "spec": {"podSelector": {"matchLabels": {
                "app.kubernetes.io/name": "n8n-checkpoint-reader", LABEL: OWNER}},
                "policyTypes": ["Ingress", "Egress"]},
        },
        "reader_active": True,
    }


MOCK = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
if name == "kubectl" and args and args[0].startswith("--request-timeout="):
    args = args[1:]
root = Path(os.environ["TEST_ROOT"])
state_file = root / "state.json"
state = json.loads(state_file.read_text())
mode = os.environ["TEST_MODE"]
job_name = os.environ["TEST_NAME"]
job_uid = os.environ["TEST_JOB_UID"]
owner = os.environ["TEST_OWNER"]
image = os.environ["TEST_IMAGE"]
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps([name, args]) + "\n")
if name == "timeout":
    assert args[:2] == ["-k", "5s"]
    os.execvp(args[3], args[3:])
elif name == "git":
    if args == ["rev-parse", "HEAD"]:
        print(os.environ["TEST_SHA"])
    elif args == ["status", "--porcelain"]:
        pass
    else:
        raise SystemExit(1)
elif name == "gh":
    print("c" * 40 if mode == "stale-main" else os.environ["TEST_SHA"])
elif name == "yq":
    print(json.dumps({"spec": {"template": {"spec": {"containers":
        [json.loads(os.environ["TEST_CONTAINER"])]}}}}))
elif name == "kubectl":
    if args[:2] == ["auth", "can-i"]:
        print("yes")
    elif "application" in args and "get" in args:
        print(json.dumps({"status": {"sync": {"status":
            "OutOfSync" if mode == "fence-unsynced" else "Synced",
            "revisions": ["4.4.0", os.environ["TEST_SHA"], os.environ["TEST_SHA"]]},
            "health": {"status": "Healthy"}}}))
    elif "deployment" in args and "get" in args:
        replicas = 1 if mode == "writer-active" else 0
        print(json.dumps({"metadata": {"generation": 1}, "spec": {"replicas": replicas},
            "status": {"replicas": replicas, "readyReplicas": replicas,
                "observedGeneration": 1}}))
    elif args[:2] == ["get", "--raw"]:
        pods = []
        if state["reader_active"]:
            pods.append({"metadata": {"name": job_name + "-abcde", "uid":
                os.environ["TEST_POD_UID"], "labels": {
                    "app.kubernetes.io/name": "n8n-checkpoint-reader",
                    "batch.kubernetes.io/job-name": job_name,
                    "homelab.stuhlmuller.dev/checkpoint-owner": owner},
                "ownerReferences": [{"controller": True, "kind": "Job",
                    "name": job_name, "uid": job_uid}]},
                "spec": {"automountServiceAccountToken": False,
                    "containers": [{"name": "reader", "image": image,
                        "volumeMounts": [{"name": "source", "mountPath": "/source",
                            "readOnly": True}]}],
                    "volumes": [{"name": "source", "persistentVolumeClaim":
                        {"claimName": "n8n", "readOnly": True}}]}})
        print(json.dumps({"kind": "PodList", "metadata": {
            "resourceVersion": "33", "continue": ""}, "items": pods}))
    elif "jobs,cronjobs" in args:
        print(json.dumps({"items": []}))
    elif "wait" in args:
        kind = "job" if "job/" + job_name in args else "policy"
        assert "--for=delete" in args
        assert "--timeout=120s" in args if kind == "job" else "--timeout=60s" in args
        if mode == kind + "-wait-stuck":
            raise SystemExit(1)
        state[kind] = None
        if kind == "job" and mode != "reader-stuck":
            state["reader_active"] = False
        state_file.write_text(json.dumps(state))
    elif "delete" in args:
        kind = "job" if "job" in args else "policy"
        assert args[args.index(kind if kind == "job" else "networkpolicy") + 1] == job_name
        assert "--wait=true" in args
        assert "--timeout=120s" in args if kind == "job" else "--timeout=60s" in args
        if kind == "job":
            assert "--cascade=foreground" in args
        if mode == kind + "-delete-conflict":
            raise SystemExit(1)
        state[kind] = None
        if kind == "job" and mode != "reader-stuck":
            state["reader_active"] = False
        state_file.write_text(json.dumps(state))
    elif "get" in args and "job" in args:
        if state["job"] is not None:
            print(json.dumps(state["job"]))
    elif "get" in args and "networkpolicy" in args:
        if state["policy"] is not None:
            print(json.dumps(state["policy"]))
    else:
        raise SystemExit("unexpected kubectl " + repr(args))
else:
    raise SystemExit("unexpected command " + name)
'''


class ResidualCleanupTests(unittest.TestCase):
    def run_case(self, mode="normal", state=None, job_uid=JOB_UID, policy_uid=POLICY_UID):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            mock = bin_dir / "mock"
            mock.write_text(MOCK)
            mock.chmod(0o755)
            for command in ("git", "gh", "yq", "kubectl", "timeout"):
                (bin_dir / command).symlink_to(mock)
            (root / "state.json").write_text(json.dumps(state or initial_state()))
            env = os.environ.copy()
            env.update({"PATH": str(bin_dir) + os.pathsep + env["PATH"],
                "TEST_ROOT": tmp, "TEST_MODE": mode, "TEST_SHA": SHA,
                "TEST_NAME": NAME, "TEST_JOB_UID": JOB_UID,
                "TEST_POD_UID": POD_UID, "TEST_OWNER": OWNER,
                "TEST_IMAGE": IMAGE, "TEST_CONTAINER": json.dumps(CONTAINER)})
            result = subprocess.run(["bash", str(SCRIPT), SHA, "123", "1",
                job_uid, policy_uid, OWNER], cwd=ROOT, env=env,
                text=True, capture_output=True, timeout=15)
            final = json.loads((root / "state.json").read_text())
            calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
            bounded = [args for command, args in calls if command == "timeout"]
            kubectls = [args for command, args in calls if command == "kubectl"]
            self.assertEqual(len(bounded), len(kubectls))
            for args in bounded:
                self.assertTrue(args[3].endswith("/kubectl"))
                action = args[4:]
                expected_cap = "155s" if ("job" in action or "job/" + NAME in action) and (
                    "delete" in action or "wait" in action) else (
                    "95s" if ("networkpolicy" in action or "networkpolicy/" + NAME in action) and (
                        "delete" in action or "wait" in action) else "45s")
                self.assertEqual(args[2], expected_cap)
            deletes = [args for command, args in calls if command == "kubectl" and
                args[0] != "auth" and "delete" in args]
            return result, final, deletes

    def test_job_then_policy_and_fence(self):
        result, final, deletes = self.run_case()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(final, {"job": None, "policy": None, "reader_active": False})
        self.assertEqual([args[args.index("delete") + 1] for args in deletes], ["job", "networkpolicy"])

    def test_policy_only_residual(self):
        state = initial_state()
        state["job"] = None
        state["reader_active"] = False
        result, final, deletes = self.run_case(state=state, job_uid="absent")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(final["policy"])
        self.assertEqual(len(deletes), 1)

    def test_job_only_residual(self):
        state = initial_state()
        state["policy"] = None
        result, final, deletes = self.run_case(state=state, policy_uid="absent")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(final["job"])
        self.assertFalse(final["reader_active"])
        self.assertEqual(len(deletes), 1)

    def test_already_absent_is_idempotent(self):
        state = {"job": None, "policy": None, "reader_active": False}
        result, final, deletes = self.run_case(state=state, job_uid="absent", policy_uid="absent")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(final, state)
        self.assertEqual(deletes, [])

    def test_foreign_and_unsafe_resources_never_deleted(self):
        for variant in ("uid", "owner", "policy"):
            with self.subTest(variant=variant):
                state = initial_state()
                if variant == "uid":
                    state["job"]["metadata"]["uid"] = POLICY_UID
                elif variant == "owner":
                    state["job"]["metadata"]["labels"][LABEL] = "foreign"
                else:
                    state["policy"]["spec"]["egress"] = [{"to": []}]
                result, final, deletes = self.run_case(state=state)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(deletes, [])
                self.assertEqual(final, state)

    def test_failed_delete_keeps_policy(self):
        for mode in ("job-delete-conflict", "reader-stuck", "policy-delete-conflict"):
            with self.subTest(mode=mode):
                result, final, deletes = self.run_case(mode=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNotNone(final["policy"])
                self.assertGreaterEqual(len(deletes), 1)

    def test_stale_main_and_unfenced_writer_never_delete(self):
        for mode in ("stale-main", "fence-unsynced", "writer-active"):
            with self.subTest(mode=mode):
                result, final, deletes = self.run_case(mode=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(final, initial_state())
                self.assertEqual(deletes, [])

    def test_unexpected_resource_when_declared_absent_never_deleted(self):
        result, final, deletes = self.run_case(job_uid="absent")
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNotNone(final["job"])
        self.assertEqual(deletes, [])

    def test_deleting_job_waits_before_policy_removal(self):
        state = initial_state()
        state["job"]["metadata"]["deletionTimestamp"] = "2026-10-31T12:00:00Z"
        result, final, deletes = self.run_case(state=state)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(final, {"job": None, "policy": None, "reader_active": False})
        self.assertEqual([args[args.index("delete") + 1] for args in deletes], ["networkpolicy"])

    def test_deleting_policy_waits_after_reader_absence(self):
        state = initial_state()
        state["job"] = None
        state["reader_active"] = False
        state["policy"]["metadata"]["deletionTimestamp"] = "2026-10-31T12:00:00Z"
        result, final, deletes = self.run_case(state=state, job_uid="absent")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(final["policy"])
        self.assertEqual(deletes, [])

    def test_both_objects_already_deleting_without_reader(self):
        state = initial_state()
        state["reader_active"] = False
        for kind in ("job", "policy"):
            state[kind]["metadata"]["deletionTimestamp"] = "2026-10-31T12:00:00Z"
        result, final, deletes = self.run_case(state=state)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(final, {"job": None, "policy": None, "reader_active": False})
        self.assertEqual(deletes, [])

    def test_stuck_deletion_and_unsafe_policy_state_fail_closed(self):
        for mode, policy_deleting, reader_active in (
            ("job-wait-stuck", False, True),
            ("policy-wait-stuck", True, False),
            ("normal", True, True),
        ):
            with self.subTest(mode=mode, reader_active=reader_active):
                state = initial_state()
                state["job"]["metadata"]["deletionTimestamp"] = "2026-10-31T12:00:00Z"
                if policy_deleting:
                    state["policy"]["metadata"]["deletionTimestamp"] = "2026-10-31T12:00:00Z"
                state["reader_active"] = reader_active
                result, final, deletes = self.run_case(mode=mode, state=state)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNotNone(final["policy"])
                self.assertEqual(deletes, [])


if __name__ == "__main__":
    unittest.main()
