#!/usr/bin/env python3
"""Reject unsafe LiteLLM rollout snapshots without cluster access."""
import copy
import contextlib
from datetime import datetime, timezone
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("release", Path(__file__).with_name("litellm-release-check.py"))
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
NOW = datetime(2026, 11, 2, 4, tzinfo=timezone.utc)
STAMP = "2026-11-02T04:00:00Z"
MIB = 1024 ** 2


def owner(kind, uid):
    return {"kind": kind, "uid": uid, "controller": True}


def pod(uid, memory="1Gi", namespace="apps"):
    return {"metadata": {"name": uid, "uid": uid, "namespace": namespace},
            "spec": {"nodeName": "acer", "containers": [{"name": "litellm", "resources": {"requests": {"memory": memory}}}]},
            "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}}


def fixture():
    node = {"metadata": {"name": "acer", "labels": {"kubernetes.io/hostname": "acer"}}, "spec": {},
            "status": {"allocatable": {"memory": "8Gi"}, "conditions": [
                {"type": name, "status": "True" if name == "Ready" else "False", "lastHeartbeatTime": STAMP}
                for name in ("Ready", "MemoryPressure", "DiskPressure", "PIDPressure")]}}
    lease = {"metadata": {"name": "acer"}, "spec": {"holderIdentity": "acer", "renewTime": STAMP}}
    gateway = pod("gateway", "0", "ai")
    gateway["metadata"]["ownerReferences"] = [owner("ReplicaSet", "rs")]
    deployment = {"metadata": {"name": "litellm", "namespace": "ai", "uid": "deploy", "generation": 1},
                  "spec": {"replicas": 1, "template": {"spec": gateway["spec"]}}, "status": {"observedGeneration": 1}}
    sets = [{"metadata": {"namespace": "ai", "uid": "rs", "ownerReferences": [owner("Deployment", "deploy")]},
             "spec": {"replicas": 1, "template": deployment["spec"]["template"]}}]
    crons = []
    for index, memory in enumerate([512, 128, 64, 128, 64, 64]):
        template = pod("template", f"{memory}Mi")
        template["spec"].pop("nodeName")
        crons.append({"metadata": {"uid": f"cron-{index}", "namespace": "apps"},
                      "spec": {"suspend": False, "concurrencyPolicy": "Forbid",
                               "jobTemplate": {"spec": {"template": template}}}})
    summary = {"node": {"nodeName": "acer", "memory": {"time": STAMP, "availableBytes": 4 * release.GIB}},
               "pods": [{"podRef": {"uid": "gateway", "namespace": "ai", "name": "gateway"},
                         "memory": {"time": STAMP, "workingSetBytes": 512 * MIB}}]}
    values = {"nodeSelector": {"kubernetes.io/hostname": "acer"}, "resources": {"requests": {"memory": "1Gi"}}}
    return [node, lease, [gateway, pod("other", "4Gi")], crons, [], deployment, sets, summary, values, NOW]


class Capacity(unittest.TestCase):
    def test_full_recurring_budget_and_both_rollout_states(self):
        data = fixture()
        self.assertEqual(release.recurring_reservation(data[3], [], data[2][1:], data[0]), 960 * MIB)
        release.check(*data)
        data[2][0]["spec"]["containers"][0]["resources"]["requests"]["memory"] = "1Gi"
        release.check(*data)

    def test_actual_headroom_credits_only_exact_fresh_serving_gateway_usage(self):
        data = fixture()
        threshold = 2 * release.GIB - 512 * MIB + 960 * MIB
        data[7]["node"]["memory"]["availableBytes"] = threshold
        release.check(*data)
        data[7]["node"]["memory"]["availableBytes"] -= 1
        with self.assertRaisesRegex(ValueError, "actual_memory_margin"):
            release.check(*data)
        for mutate in (lambda d: d[7]["pods"][0]["podRef"].update(uid="other"),
                       lambda d: d[7]["pods"][0]["memory"].update(time="2026-11-02T03:59:00Z"),
                       lambda d: d[7]["pods"][0]["memory"].update(workingSetBytes=2 * release.GIB),
                       lambda d: d[7].update(pods=d[7]["pods"] * 2)):
            changed = fixture()
            mutate(changed)
            with self.assertRaises(ValueError):
                release.check(*changed)

    def test_recurring_active_job_counted_once_but_deleting_pod_not_reused(self):
        data = fixture()
        job = {"metadata": {"uid": "job", "namespace": "apps", "ownerReferences": [owner("CronJob", "cron-0")]}, "spec": {"template": pod("job-template", "512Mi")}}
        active = pod("job-pod", "512Mi")
        active["metadata"]["ownerReferences"] = [owner("Job", "job")]
        self.assertEqual(release.recurring_reservation(data[3], [job], [active], data[0]), 448 * MIB)
        active["metadata"]["deletionTimestamp"] = STAMP
        self.assertEqual(release.recurring_reservation(data[3], [job], [active], data[0]), 960 * MIB)
        active["metadata"].pop("deletionTimestamp")
        active["metadata"]["namespace"] = "other"
        self.assertEqual(release.recurring_reservation(data[3], [job], [active], data[0]), 960 * MIB)

    def test_old_active_job_template_retains_demand_without_a_pod(self):
        data = fixture()
        data[0]["status"]["allocatable"]["memory"] = "6656Mi"
        data[3] = data[3][:1]
        old = {"metadata": {"uid": "old-job", "namespace": "apps", "ownerReferences": [owner("CronJob", "cron-0")]},
               "spec": {"template": pod("template", "2Gi")}, "status": {"active": 1}}
        data[4] = [old]
        for suspended, moved in ((False, False), (True, False), (False, True)):
            data[3][0]["spec"]["suspend"] = suspended
            if moved:
                data[3][0]["spec"]["jobTemplate"]["spec"]["template"]["spec"]["nodeName"] = "other"
            with self.assertRaisesRegex(ValueError, "two_pod_reservation"):
                release.check(*data)
        data[3][0]["spec"]["suspend"] = False
        old["status"] = {"conditions": [{"type": "Failed", "status": "True"}]}
        release.check(*data)
        old["status"] = {"active": 1}
        duplicate = copy.deepcopy(old)
        duplicate["metadata"]["uid"] = "second-job"
        data[4].append(duplicate)
        with self.assertRaisesRegex(ValueError, "recurring_overlap"):
            release.check(*data)

    def test_absent_recurring_jobs_cannot_create_false_headroom(self):
        data = fixture()
        data[0]["status"]["allocatable"]["memory"] = "6656Mi"
        with self.assertRaisesRegex(ValueError, "two_pod_reservation"):
            release.check(*data)
        data[3] = []  # Explicitly demonstrates why the complete CronJob inventory matters.
        release.check(*data)

    def test_init_sidecar_overhead_and_terminating_pods_count(self):
        data = fixture()
        other = data[2][1]
        other["metadata"]["deletionTimestamp"] = STAMP
        other["spec"]["initContainers"] = [{"name": "sidecar", "restartPolicy": "Always",
                                                 "resources": {"requests": {"memory": "1Gi"}}},
                                                {"name": "setup", "resources": {"requests": {"memory": "6Gi"}}}]
        other["spec"]["overhead"] = {"memory": "128Mi"}
        self.assertEqual(release.CAPACITY["pod_memory_request"](other), 7 * release.GIB + 128 * MIB)
        with self.assertRaisesRegex(ValueError, "two_pod_reservation"):
            release.check(*data)
        other["status"]["phase"] = "Succeeded"
        release.check(*data)

    def test_fail_closed_conditions_strategy_metrics_resize_and_identity(self):
        mutations = [
            lambda d: d[0]["status"]["conditions"][0].update(status="Unknown"),
            lambda d: d[0]["status"]["conditions"][0].update(lastHeartbeatTime="2026-11-02T03:00:00Z"),
            lambda d: d[0]["spec"].update(unschedulable=True),
            lambda d: d[1]["spec"].update(renewTime="2026-11-02T03:00:00Z"),
            lambda d: d[7]["node"]["memory"].update(time="2026-11-02T03:00:00Z"),
            lambda d: d[7]["node"]["memory"].update(availableBytes=release.GIB),
            lambda d: d[7]["node"].update(nodeName="other"),
            lambda d: d[2][1]["status"].update(resize="InProgress"),
            lambda d: d[2][1]["spec"].pop("nodeName"),
            lambda d: d[2][1]["spec"].update(resources=False),
            lambda d: d[2][1]["spec"]["containers"][0].update(resources=False),
            lambda d: d[2][1]["spec"].update(schedulerName="custom"),
            lambda d: d[5]["spec"].update(strategy={"type": "Recreate"}),
            lambda d: d[5]["spec"].update(replicas=2),
            lambda d: d[6][0]["metadata"]["ownerReferences"][0].update(uid="other"),
            lambda d: d[3][0]["spec"].update(concurrencyPolicy="Allow"),
            lambda d: d[3][0]["spec"]["jobTemplate"]["spec"].update(parallelism=2),
            lambda d: d[3][0]["spec"]["jobTemplate"]["spec"].update(completionMode="Indexed"),
            lambda d: d[8]["resources"]["requests"].update(memory="512Mi"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                data = fixture()
                mutate(data)
                with self.assertRaises(ValueError):
                    release.check(*data)

    def test_complete_lists_reject_pagination_duplicates_and_bad_kind(self):
        document = {"kind": "PodList", "metadata": {"resourceVersion": "1"}, "items": [pod("one")]}
        self.assertEqual(len(release.items(document, "Pod")), 1)
        for mutation in (lambda d: d["metadata"].update(continue_="unused", **{"continue": "token"}),
                         lambda d: d.update(items=d["items"] * 2), lambda d: d.update(kind="List")):
            changed = copy.deepcopy(document)
            mutation(changed)
            with self.assertRaises(ValueError):
                release.items(changed, "Pod")

    def test_failed_live_read_withholds_private_output(self):
        changed = subprocess.CompletedProcess([], 0, "clusters/homelab/apps/litellm/values.yaml\0")
        denied = subprocess.CalledProcessError(1, "kubectl", output="PRIVATE_FIXTURE", stderr="PRIVATE_FIXTURE")
        output = io.StringIO()
        with patch("sys.argv", ["check", "--base-ref", "origin/main"]), \
             patch.object(release.subprocess, "run", return_value=changed), \
             patch.object(release, "read_json", side_effect=denied), contextlib.redirect_stderr(output):
            self.assertEqual(release.main(), 1)
        self.assertNotIn("PRIVATE_FIXTURE", output.getvalue())

    def test_workflow_scopes_runtime_and_helper_changes_but_not_docs(self):
        root = Path(__file__).parents[2]
        workflow = (root / ".github/workflows/terragrunt-plan.yml").read_text()
        classifier = workflow.split("          requires_live_plan=false", 1)[1].split('          echo "requires-live-plan=', 1)[0]
        classifier = "requires_live_plan=false" + classifier + '\nprintf "%s %s" "$requires_live_plan" "$requires_runtime_check"'
        paths = ["clusters/homelab/apps/litellm/values.yaml", "IaC/homelab/us-west-2/apps/litellm/stack.hcl",
                 "scripts/ci/litellm-release-check.py", "scripts/network-policy-candidate-report.py",
                 ".github/workflows/terragrunt-plan.yml"]
        for path in paths + ["clusters/homelab/apps/litellm/README.md"]:
            result = subprocess.run(["bash", "-c", classifier], env={**os.environ, "changed_paths": path},
                                    capture_output=True, text=True, check=True)
            expected = not path.endswith(".md")
            self.assertEqual(release.runtime_changed([path]), expected)
            self.assertEqual(result.stdout.strip(), "true true" if expected else "false false")
        self.assertIn('python3 -I scripts/ci/litellm-release-check.py --base-ref "origin/$BASE_REF"', workflow)


if __name__ == "__main__":
    unittest.main()
