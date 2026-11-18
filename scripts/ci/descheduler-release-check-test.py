#!/usr/bin/env python3
"""Offline counterexamples for the read-only one-eviction activation check."""
import copy
import contextlib
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("release", Path(__file__).with_name("descheduler-release-check.py"))
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
NOW = datetime.now(timezone.utc)
STAMP = NOW.isoformat()
MIB = 1024 ** 2


def pod(name, node="acer", owner="replicas", kind="ReplicaSet"):
    return {"metadata": {"name": name, "namespace": "fixture", "uid": name,
                         "ownerReferences": [{"kind": kind, "uid": owner, "controller": True}]},
            "spec": {"nodeName": node, "containers": [{"name": "app", "resources": {
                "requests": {"memory": "128Mi"}, "limits": {"memory": "256Mi"}}}]},
            "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}}


def fixture():
    nodes, leases, summaries = [], [], {}
    pods = [pod("one"), pod("two")]
    for name in sorted(release.NODES):
        nodes.append({"metadata": {"name": name, "uid": name, "labels": {"kubernetes.io/hostname": name}},
                      "spec": {}, "status": {"nodeInfo": {"bootID": name}, "allocatable": {"memory": "2Gi"},
                      "capacity": {"memory": "2Gi"},
                      "conditions": [{"type": kind, "status": status, "lastHeartbeatTime": STAMP} for kind, status in (
                          ("Ready", "True"), ("MemoryPressure", "False"),
                          ("DiskPressure", "False"), ("PIDPressure", "False"))]}})
        leases.append({"metadata": {"name": name, "uid": "lease-" + name,
                                    "ownerReferences": [{"kind": "Node", "uid": name}]},
                       "spec": {"holderIdentity": name, "renewTime": STAMP}})
        summaries[name] = {"node": {"nodeName": name, "memory": {"time": STAMP, "availableBytes": 1024 * MIB}},
                           "pods": [{"podRef": {key: p["metadata"][key] for key in ("name", "namespace", "uid")},
                                     "memory": {"time": STAMP, "workingSetBytes": 128 * MIB}}
                                    for p in pods if p["spec"]["nodeName"] == name]}
    return nodes, leases, pods, [], [], summaries


def cron_fixture():
    data = fixture()
    template = copy.deepcopy(pod("template"))
    template["spec"].pop("nodeName")
    data[3].append({"metadata": {"name": "backup", "namespace": "fixture", "uid": "cron"},
                    "spec": {"concurrencyPolicy": "Forbid", "jobTemplate": {"spec": {"template": template}}}})
    return data


class Activation(unittest.TestCase):
    def check(self, data):
        release.check(*data, NOW)

    def test_supported_one_eviction_and_recurring_budget(self):
        self.check(fixture())
        self.check(cron_fixture())

    def test_node_health_inventory_and_lease_fail_closed(self):
        changes = [
            lambda d: d[0].pop(),
            lambda d: d[0][0]["status"]["conditions"].pop(0),
            lambda d: d[0][0]["status"]["conditions"][0].update(status="Unknown"),
            lambda d: d[0][0]["status"]["conditions"][1].update(status="True"),
            lambda d: d[0][0]["spec"].update(unschedulable=True),
            lambda d: d[1][0]["metadata"]["ownerReferences"][0].update(uid="old-node"),
            lambda d: d[1][0]["spec"].update(renewTime=(NOW - timedelta(seconds=91)).isoformat()),
            lambda d: d[1][0]["spec"].update(renewTime=(NOW + timedelta(seconds=1)).isoformat()),
            lambda d: d[0][0]["status"]["conditions"][0].update(lastHeartbeatTime=(NOW - timedelta(seconds=361)).isoformat()),
        ]
        for change in changes:
            with self.subTest(change=change):
                data = fixture()
                change(data)
                with self.assertRaises(ValueError):
                    self.check(data)

    def test_unsettled_placements_and_unknown_demand_fail(self):
        changes = [
            lambda p: p["status"].update(phase="Pending"),
            lambda p: p["metadata"].update(deletionTimestamp=STAMP),
            lambda p: p["spec"].update(nodeName="unknown"),
            lambda p: p["status"]["conditions"][0].update(status="False"),
            lambda p: p["spec"]["containers"][0]["resources"].pop("limits"),
            lambda p: p["spec"]["containers"][0]["resources"]["limits"].update(memory="0"),
            lambda p: p["spec"].update(affinity={"podAffinity": {}}),
            lambda p: p["spec"].update(schedulerName="other"),
            lambda p: p["spec"]["containers"][0].update(ports=[{"hostPort": 80}]),
            lambda p: p["metadata"].update(annotations={"descheduler.alpha.kubernetes.io/evict": "true"}),
        ]
        for change in changes:
            with self.subTest(change=change):
                data = fixture()
                change(data[2][0])
                with self.assertRaises(ValueError):
                    self.check(data)

    def test_zero_request_still_reserves_explicit_limit_and_init_demand(self):
        data = fixture()
        data[2][0]["spec"]["containers"][0]["resources"]["requests"]["memory"] = "0"
        data[2][0]["spec"]["initContainers"] = [{"name": "init", "resources": {"limits": {"memory": "512Mi"}}}]
        data[5]["zimaboard-0"]["node"]["memory"]["availableBytes"] = 767 * MIB
        with self.assertRaisesRegex(ValueError, "physical"):
            self.check(data)
        data[5]["zimaboard-0"]["node"]["memory"]["availableBytes"] = 768 * MIB
        self.check(data)

    def test_native_protected_pods_not_moving_candidates(self):
        for protection in ("bare", "daemon", "critical", "pvc", "local", "single"):
            with self.subTest(protection=protection):
                data = fixture()
                p = data[2][0]
                if protection == "bare":
                    p["metadata"]["ownerReferences"] = []
                elif protection == "daemon":
                    p["metadata"]["ownerReferences"][0]["kind"] = "DaemonSet"
                elif protection == "critical":
                    p["spec"]["priority"] = 2000000000
                elif protection in ("pvc", "local"):
                    p["spec"]["volumes"] = [{"persistentVolumeClaim" if protection == "pvc" else "emptyDir": {}}]
                else:
                    p["metadata"]["ownerReferences"][0]["uid"] = "single"
                p["spec"]["containers"][0]["resources"].pop("limits")
                self.check(data)

    def test_request_and_physical_headroom_are_independent(self):
        for field in ("request", "physical"):
            data = fixture()
            if field == "request":
                data[0][1]["status"]["allocatable"]["memory"] = "127Mi"
            else:
                data[5]["zimaboard-0"]["node"]["memory"]["availableBytes"] = 255 * MIB
            with self.assertRaisesRegex(ValueError, "insufficient_" + field):
                self.check(data)

    def test_summary_identity_freshness_and_measurement_bounds(self):
        for change in (
            lambda s: s["node"].update(nodeName="old-node"),
            lambda s: s["node"]["memory"].update(time=(NOW - timedelta(seconds=121)).isoformat()),
            lambda s: s["node"]["memory"].update(availableBytes=True),
            lambda s: s["pods"][0]["podRef"].update(uid="old-pod"),
            lambda s: s["pods"][0]["memory"].update(workingSetBytes=257 * MIB),
        ):
            data = fixture()
            change(data[5]["acer"])
            with self.assertRaises(ValueError):
                self.check(data)

    def test_cron_limits_overlap_and_unclassified_jobs(self):
        for change in (
            lambda d: d[3][0]["spec"].update(concurrencyPolicy="Allow"),
            lambda d: d[3][0]["spec"].update(suspend="false"),
            lambda d: d[3][0]["spec"]["jobTemplate"]["spec"].update(parallelism=2),
            lambda d: d[3][0]["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["resources"].pop("limits"),
            lambda d: d[4].append({"metadata": {"uid": "unowned", "namespace": "fixture"}, "spec": {}}),
        ):
            data = cron_fixture()
            change(data)
            with self.assertRaises(ValueError):
                self.check(data)

    def test_suspended_moved_cron_still_reserves_old_active_job(self):
        data = cron_fixture()
        cron = data[3][0]
        job = {"metadata": {"uid": "job", "namespace": "fixture", "ownerReferences": [
            {"kind": "CronJob", "uid": "cron", "controller": True}]},
            "spec": copy.deepcopy(cron["spec"]["jobTemplate"]["spec"])}
        data[4].append(job)
        cron["spec"]["suspend"] = True
        cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["nodeSelector"] = {"kubernetes.io/hostname": "elsewhere"}
        data[5]["zimaboard-0"]["node"]["memory"]["availableBytes"] = 511 * MIB
        with self.assertRaisesRegex(ValueError, "physical"):
            self.check(data)
        data[5]["zimaboard-0"]["node"]["memory"]["availableBytes"] = 512 * MIB
        self.check(data)

    def test_active_job_usage_is_credited_once(self):
        data = cron_fixture()
        cron = data[3][0]
        job = {"metadata": {"uid": "job", "namespace": "fixture", "ownerReferences": [
            {"kind": "CronJob", "uid": "cron", "controller": True}]},
            "spec": copy.deepcopy(cron["spec"]["jobTemplate"]["spec"])}
        data[4].append(job)
        p = pod("job-pod", "zimaboard-0", "job", "Job")
        data[2].append(p)
        data[5]["zimaboard-0"]["pods"].append({"podRef": {key: p["metadata"][key] for key in ("name", "namespace", "uid")},
                                               "memory": {"time": STAMP, "workingSetBytes": 128 * MIB}})
        data[5]["zimaboard-0"]["node"]["memory"]["availableBytes"] = 384 * MIB
        self.check(data)
        data[5]["zimaboard-0"]["node"]["memory"]["availableBytes"] -= 1
        with self.assertRaisesRegex(ValueError, "physical"):
            self.check(data)
        # Admission can increase the running Job Pod beyond its template contract.
        p["spec"]["containers"][0]["resources"]["limits"]["memory"] = "512Mi"
        data[5]["zimaboard-0"]["node"]["memory"]["availableBytes"] = 384 * MIB
        with self.assertRaisesRegex(ValueError, "physical"):
            self.check(data)
        data[5]["zimaboard-0"]["node"]["memory"]["availableBytes"] = 640 * MIB
        self.check(data)

    def test_resident_job_demand_survives_ineligible_template(self):
        for reason in ("new-taint", "admission-selector"):
            with self.subTest(reason=reason):
                data = cron_fixture()
                cron = data[3][0]
                job = {"metadata": {"uid": "job", "namespace": "fixture", "ownerReferences": [
                    {"kind": "CronJob", "uid": "cron", "controller": True}]},
                    "spec": copy.deepcopy(cron["spec"]["jobTemplate"]["spec"])}
                data[4].append(job)
                resident = pod("resident-job", "zimaboard-0", "job", "Job")
                resident["spec"]["containers"][0]["resources"]["limits"]["memory"] = "512Mi"
                data[2].append(resident)
                data[5]["zimaboard-0"]["pods"].append({
                    "podRef": {key: resident["metadata"][key] for key in ("name", "namespace", "uid")},
                    "memory": {"time": STAMP, "workingSetBytes": 128 * MIB}})
                if reason == "new-taint":
                    node = next(n for n in data[0] if n["metadata"]["name"] == "zimaboard-0")
                    node["spec"]["taints"] = [{"key": "reserved", "value": "yes", "effect": "NoSchedule"}]
                    for movable in data[2][:2]:
                        movable["spec"]["tolerations"] = [{"key": "reserved", "value": "yes"}]
                else:
                    for template in (cron["spec"]["jobTemplate"]["spec"], job["spec"]):
                        template["template"]["spec"]["nodeSelector"] = {"kubernetes.io/hostname": "acer"}
                    resident["spec"]["nodeSelector"] = {"kubernetes.io/hostname": "zimaboard-0"}
                memory = data[5]["zimaboard-0"]["node"]["memory"]
                for available in (256, 639):
                    memory["availableBytes"] = available * MIB
                    with self.assertRaisesRegex(ValueError, "physical"):
                        self.check(data)
                memory["availableBytes"] = 640 * MIB
                self.check(data)

    def test_taints_limit_destinations_and_require_exact_tolerations(self):
        data = cron_fixture()
        node = next(n for n in data[0] if n["metadata"]["name"] == "zimaboard-0")
        node["spec"]["taints"] = [{"key": "reserved", "value": "control", "effect": "NoSchedule"}]
        data[5]["zimaboard-0"]["node"]["memory"]["availableBytes"] = 0
        self.check(data)  # Neither the movable Pod nor CronJob tolerates this node.
        for effect in ("NoSchedule", "NoExecute"):
            node["spec"]["taints"][0]["effect"] = effect
            for toleration, expected in (({"key": "reserved", "value": "wrong"}, False),
                                         ({"key": "reserved", "value": "control"}, True),
                                         ({"key": "reserved", "operator": "Exists", "effect": effect}, True),
                                         ({"operator": "Exists"}, True),
                                         ({"operator": "Exists", "effect": "PreferNoSchedule"}, False)):
                self.assertEqual(release.eligible({"tolerations": [toleration]}, node), expected)
        node["spec"]["taints"][0]["effect"] = "PreferNoSchedule"
        self.assertTrue(release.eligible({}, node))
        with self.assertRaises(ValueError):
            release.eligible({"tolerations": [{"operator": "unknown"}]}, node)

    def test_job_node_name_cannot_bypass_taint_filter(self):
        data = cron_fixture()
        for node in data[0]:
            node["spec"]["taints"] = [{"key": "reserved", "value": "yes", "effect": "NoSchedule"}]
        for movable in data[2]:
            movable["spec"]["tolerations"] = [{"key": "reserved", "value": "yes"}]
        data[3][0]["spec"]["jobTemplate"]["spec"]["template"]["spec"]["nodeName"] = "zimaboard-0"
        with self.assertRaisesRegex(ValueError, "unsupported_job_placement"):
            self.check(data)

    def test_in_place_status_request_and_limit_mismatch_fail(self):
        for resources in ({"requests": {"memory": "256Mi"}}, {"limits": {"memory": "512Mi"}}):
            data = fixture()
            data[2][0]["status"]["containerStatuses"] = [{"name": "app", "resources": resources}]
            with self.assertRaises(ValueError):
                self.check(data)
        data = fixture()
        data[2][0]["status"]["containerStatuses"] = [{"name": "app", "allocatedResources": {"memory": "256Mi"}}]
        with self.assertRaises(ValueError):
            self.check(data)

    def test_collection_completeness(self):
        good = {"kind": "PodList", "metadata": {"resourceVersion": "1"}, "items": [pod("one")]}
        release.items(good, "Pod")
        for change in (lambda d: d.update(kind="List"), lambda d: d["metadata"].clear(),
                       lambda d: d["metadata"].update(continue_="ignored", **{"continue": "next"}),
                       lambda d: d["items"].append(copy.deepcopy(d["items"][0]))):
            data = copy.deepcopy(good)
            change(data)
            with self.assertRaises(ValueError):
                release.items(data, "Pod")

    def test_failures_withhold_private_command_output(self):
        changed = subprocess.CompletedProcess([], 0, "clusters/homelab/apps/descheduler/values.yaml\0")
        with patch("sys.argv", ["check", "--base-ref", "origin/main"]), \
             patch.object(release.subprocess, "run", side_effect=[changed, subprocess.CalledProcessError(
                 1, "yq", output="PRIVATE_FIXTURE", stderr="PRIVATE_FIXTURE")]), \
             contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(release.main(), 1)
        self.assertNotIn("PRIVATE_FIXTURE", output.getvalue())

    def test_workflow_scope_runtime_helpers_and_docs(self):
        workflow = (Path(__file__).parents[2] / ".github/workflows/terragrunt-plan.yml").read_text()
        body = workflow.split("          requires_live_plan=false", 1)[1].split('          echo "requires-live-plan=', 1)[0]
        body = 'requires_live_plan=false' + body + '\nprintf "%s %s" "$requires_live_plan" "$requires_runtime_check"'
        for path in ("clusters/homelab/apps/descheduler/values.yaml", "IaC/homelab/us-west-2/apps/descheduler/stack.hcl",
                     "scripts/ci/descheduler-release-check.py", "scripts/ci/descheduler-policy-check.py",
                     ".github/workflows/terragrunt-plan.yml", "clusters/homelab/apps/descheduler/README.md"):
            result = subprocess.run(["bash", "-c", body], env={**os.environ, "changed_paths": path},
                                    capture_output=True, text=True, check=True)
            expected = not path.endswith(".md")
            self.assertEqual(release.runtime_changed([path]), expected)
            self.assertEqual(result.stdout.strip(), "true true" if expected else "false false")
        self.assertIn('python3 -I scripts/ci/descheduler-release-check.py --base-ref "origin/$BASE_REF"', workflow)


if __name__ == "__main__":
    unittest.main()
