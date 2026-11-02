#!/usr/bin/env python3
"""Offline decision/one-shot regression; no live commands or credentials."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("recovery", ROOT / "scripts/zimaboard-2-incident-recovery.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def stamp(seconds=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def ref(kind, name, uid):
    return {"kind": kind, "name": name, "uid": uid, "controller": True}


def obj(name, namespace="ai", uid=None):
    return {"metadata": {"name": name, "namespace": namespace, "uid": uid or name + "-uid", "generation": 1},
            "spec": {}, "status": {}}


def pod(name, namespace, node, owner, spec=None):
    value = obj(name, namespace)
    value["metadata"]["ownerReferences"] = [owner]
    value["spec"] = {"nodeName": node, "containers": [{"name": "app", "image": "fixture", "resources": {"requests": {"memory": "1Gi"}}}], **(spec or {})}
    value["status"] = {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}
    return value


class FakeReader:
    def __init__(self):
        self.client = {"path": "/synthetic/talosctl", "version": "v1.11.3", "sha256": "a" * 64}
        self.kube, self.calls, self.commands = ["never-live-kubectl"], [], []
        self.objects = {}
        self.nodes = []
        for name in [*M.PEERS, M.NODE]:
            value = obj(name, "", M.NODE_UID if name == M.NODE else name + "-uid")
            value["metadata"]["labels"] = {"kubernetes.io/hostname": name}
            value["spec"] = {"taints": [{"key": "node.kubernetes.io/unreachable", "effect": "NoSchedule"}]}
            value["status"] = {"nodeInfo": {"osImage": "Talos (v1.11.3)", "bootID": M.BOOT},
                               "addresses": [{"address": M.ADDRESS, "type": "InternalIP"}],
                               "allocatable": {"memory": "8Gi"}, "conditions": [
                                   {"type": "Ready", "status": "Unknown" if name == M.NODE else "True", "reason": "NodeStatusUnknown"},
                                   {"type": "MemoryPressure", "status": "False"}]}
            self.nodes.append(value)
        self.leases = [{"metadata": {"name": node["metadata"]["name"]}, "spec": {"renewTime": stamp(-120 if node["metadata"]["name"] == M.NODE else -1)}} for node in self.nodes]
        self.deployment = obj("litellm")
        template = {"nodeSelector": {"kubernetes.io/hostname": "acer"}, "containers": [{"name": "app", "image": "fixture", "resources": {"requests": {"memory": "1Gi"}}}]}
        self.deployment["spec"] = {"replicas": 1, "template": {"spec": template}}
        self.deployment["status"] = {"observedGeneration": 1, "availableReplicas": 1}
        self.rs = obj("litellm-current")
        self.rs["metadata"]["ownerReferences"] = [ref("Deployment", "litellm", "litellm-uid")]
        self.rs["spec"] = {"replicas": 1, "template": {"spec": copy.deepcopy(template)}}
        self.gateway = pod("gateway", "ai", "acer", ref("ReplicaSet", "litellm-current", self.rs["metadata"]["uid"]), copy.deepcopy(template))
        self.target = pod("flannel", "kube-system", M.NODE, ref("DaemonSet", "kube-flannel", "flannel-ds"))
        self.pods = [self.gateway, self.target]
        self.sets = [self.rs]
        for namespace, name in [("kube-system", "coredns"), ("istio-system", "istiod"),
                                ("octelium", "emergency-octelium-admin-api"), ("octelium", "emergency-octelium-auth-api"),
                                ("octelium", "emergency-octelium-ingress")]:
            rs = obj(name + "-rs", namespace)
            rs["metadata"]["ownerReferences"] = [ref("Deployment", name, name + "-uid")]
            self.sets.append(rs)
            ready = pod(name + "-pod", namespace, "zimaboard-0", ref("ReplicaSet", rs["metadata"]["name"], rs["metadata"]["uid"]))
            self.pods.append(ready)
        self.objects[("kube-system", "DaemonSet", "kube-flannel")] = obj("kube-flannel", "kube-system", "flannel-ds")
        self.declared = {"nodeSelector": template["nodeSelector"], "resources": {"requests": {"memory": "1Gi"}}}
        self.cron = obj("renovate", "automation")
        self.cron["spec"] = {"suspend": False, "schedule": "0 * * * *", "concurrencyPolicy": "Forbid", "jobTemplate": {"spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": "acer"}, "containers": [{"name": "renovate", "resources": {"requests": {"memory": "512Mi"}}}]}}}}}
        self.declared_cron = copy.deepcopy(self.cron)
        self.jobs = []
        self.crons = [self.cron]
        self.memory = 6 * M.GIB
        self.boot = M.BOOT
        self.recovered = False
        self.fail_reboot = False
        self.before_reboot = lambda: None

    def get(self, namespace, kind, *arguments):
        self.calls.append((namespace, kind, *arguments))
        if kind == "nodes":
            return {"items": self.nodes}
        if kind == "node":
            return self.nodes[-1]
        if kind == "pods":
            return {"items": self.pods}
        if kind == "leases":
            return {"items": self.leases}
        if kind == "application":
            return {}
        if kind == "replicasets":
            return {"items": [item for item in self.sets if item["metadata"]["namespace"] == namespace]}
        if kind == "cronjobs":
            return {"items": self.crons}
        if kind == "cronjob":
            return self.cron
        if kind == "jobs":
            return {"items": self.jobs}
        key = (namespace, kind, *arguments)
        if key in self.objects:
            return self.objects[key]
        if kind == "deployment":
            if arguments[0] == "litellm":
                return self.deployment
            value = obj(arguments[0], namespace)
            value["status"] = {"observedGeneration": 1, "availableReplicas": 1}
            return value
        raise AssertionError(f"Unexpected fixture read {key}")

    def run(self, command, timeout=25):
        self.commands.append(command)
        if command[0] == "yq":
            return json.dumps(self.declared_cron if "renovate" in command[-1] else self.declared)
        if command[-1] == "/readyz":
            return "ok"
        raise AssertionError("Unexpected process command")

    def client_matches(self):
        pass

    def talos(self, address, *arguments, timeout=25):
        self.commands.append((address, *arguments))
        if arguments[0] == "reboot":
            self.before_reboot()
            if self.fail_reboot:
                raise subprocess.TimeoutExpired("mock-reboot", timeout)
            return ""
        if arguments == ("read", "/proc/sys/kernel/random/boot_id"):
            return self.boot
        if arguments == ("read", "/proc/meminfo"):
            return f"MemTotal: 9000000 kB\nMemAvailable: {self.memory // 1024} kB\n"
        if arguments == ("get", "machinestatus", "-o", "json"):
            return json.dumps({"spec": {"stage": "running"}})
        if arguments == ("get", "services", "-o", "json"):
            return "\n".join(json.dumps({"metadata": {"id": name}, "spec": {"running": True, "unknown": False, "healthy": name != "kubelet" or address != M.ADDRESS or self.recovered}}) for name in ["apid", "machined", "containerd", "cri", "kubelet", "etcd"])
        raise AssertionError("Unexpected Talos command")

    def secret_uid(self, name):
        self.calls.append(("tailscale", "secret-metadata-only", name))
        return "identity-uid"


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        os.chmod(self.directory, 0o700)
        self.args = SimpleNamespace(reviewed_sha="a" * 40, snapshot_dir=self.directory,
                                    plan=self.directory / "plan.json", approve_plan_sha256=None)
        payload = b"x" * 4096
        (self.directory / M.BACKUP["SNAPSHOT"]).write_bytes(payload + hashlib.sha256(payload).digest())
        os.chmod(self.directory / M.BACKUP["SNAPSHOT"], 0o600)
        self.snapshot = {"format": 1, "snapshot": M.BACKUP["SNAPSHOT"], "created_at": stamp(-10),
                         "source_node": "10.1.0.199", "integrity": M.BACKUP["snapshot_digest"](self.directory / M.BACKUP["SNAPSHOT"])}
        path = self.directory / M.BACKUP["MANIFEST"]
        path.write_text(json.dumps(self.snapshot))
        os.chmod(path, 0o600)
        # The imported GitOps verifier has its own full source/revision tests.
        patcher = patch.dict(M.GITOPS, {"application": lambda *args: None})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.read = FakeReader()

    def inspect(self):
        return M.inspect(self.args, self.read)

    def test_complete_synthetic_preflight_and_recurring_gap(self):
        result = self.inspect()
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["prevention_and_capacity"]["recurring_reservation_bytes"], 512 * 1024 ** 2)
        self.assertNotIn("containers", json.dumps(result))
        self.assertFalse(any("reboot" in command for command in self.read.commands))

    def test_capacity_rejects_transient_hourly_gap(self):
        self.nodes_acer()["status"]["allocatable"]["memory"] = "2300Mi"
        self.assertIn("prevention_and_capacity_unverified", self.inspect()["blockers"])

    def nodes_acer(self):
        return next(node for node in self.read.nodes if node["metadata"]["name"] == "acer")

    def test_other_recurring_backups_reserved_and_running_job_not_double_counted(self):
        backup = copy.deepcopy(self.read.cron)
        backup["metadata"].update(name="backup", namespace="data", uid="backup-uid")
        backup["spec"]["jobTemplate"]["spec"]["template"]["spec"]["nodeSelector"] = {}
        backup["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]["memory"] = "128Mi"
        self.read.crons.append(backup)
        reserve = M.recurring_reservation(self.read, [], self.nodes_acer())
        self.assertEqual(reserve, 640 * 1024 ** 2)
        job = obj("backup-job", "data")
        job["metadata"]["ownerReferences"] = [ref("CronJob", "backup", "backup-uid")]
        self.read.jobs = [job]
        active = pod("backup-pod", "data", "acer", ref("Job", "backup-job", "backup-job-uid"),
                     copy.deepcopy(backup["spec"]["jobTemplate"]["spec"]["template"]["spec"]))
        self.assertEqual(M.recurring_reservation(self.read, [active], self.nodes_acer()), 512 * 1024 ** 2)
        active["metadata"]["deletionTimestamp"] = stamp(-1)
        self.assertEqual(M.recurring_reservation(self.read, [active], self.nodes_acer()), 640 * 1024 ** 2)
        for key, value in [("parallelism", 4), ("completions", 4), ("completionMode", "Indexed")]:
            spec = backup["spec"]["jobTemplate"]["spec"]
            spec[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "parallel_recurring_job"):
                M.recurring_reservation(self.read, [], self.nodes_acer())
            del spec[key]
        job["spec"]["parallelism"] = 4
        with self.assertRaisesRegex(ValueError, "active_parallel_recurring_job"):
            M.recurring_reservation(self.read, [], self.nodes_acer())
        job["spec"].clear()
        backup["spec"]["concurrencyPolicy"] = "Allow"
        with self.assertRaisesRegex(ValueError, "unbounded_recurring_overlap"):
            M.recurring_reservation(self.read, [], self.nodes_acer())

    def test_preflight_failures(self):
        mutations = [
            lambda: self.read.nodes[-1]["metadata"].update(uid="wrong"),
            lambda: setattr(self.read, "boot", "another-boot"),
            lambda: self.read.leases[0]["spec"].update(renewTime=stamp(-100)),
            lambda: self.read.nodes[0]["status"]["conditions"][1].update(status="True"),
            lambda: self.read.nodes[-1]["spec"].update(taints=[]),
            lambda: self.read.declared.update(nodeSelector={}),
            lambda: self.read.deployment["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"].update(memory="128Mi"),
            lambda: self.read.gateway["status"]["conditions"][0].update(status="False"),
            lambda: self.read.cron["spec"].update(suspend=True),
            lambda: setattr(self.read, "memory", M.GIB),
            lambda: setattr(self.args, "snapshot_dir", None),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.read, self.args.snapshot_dir = FakeReader(), self.directory
                mutate()
                self.assertTrue(self.inspect()["blockers"])
                self.assertFalse(any("reboot" in command for command in self.read.commands))

    def test_snapshot_staleness_and_integrity(self):
        self.snapshot["created_at"] = stamp(-21601)
        (self.directory / M.BACKUP["MANIFEST"]).write_text(json.dumps(self.snapshot))
        self.assertIn("snapshot_unverified", self.inspect()["blockers"])
        (self.directory / M.BACKUP["SNAPSHOT"]).write_bytes(b"corrupt")
        self.assertIn("snapshot_unverified", self.inspect()["blockers"])

    def test_one_shot_timeout_consumes_before_rpc_and_no_retry(self):
        plan = self.inspect()
        M.MAINTENANCE["save_inspection"](self.args.plan, plan)
        self.args.approve_plan_sha256 = M.digest(plan)
        self.read.fail_reboot = True
        def check_attempt_already_persisted():
            attempt = M.MAINTENANCE["read_private_json"](self.directory / M.ATTEMPT)
            self.assertEqual(attempt["plan_sha256"], M.digest(plan))
            self.assertEqual((self.directory / M.ATTEMPT).stat().st_mode & 0o777, 0o600)
        self.read.before_reboot = check_attempt_already_persisted
        with self.assertRaises(subprocess.TimeoutExpired):
            M.execute(self.args, self.read, self.directory)
        attempt = M.MAINTENANCE["read_private_json"](self.directory / M.ATTEMPT)
        self.assertEqual(attempt["status"], "submitted-or-unknown")
        with self.assertRaisesRegex(ValueError, "attempt_already_consumed"):
            M.execute(self.args, self.read, self.directory)
        reboot = [command for command in self.read.commands if "reboot" in command]
        self.assertEqual(reboot, [(M.ADDRESS, "reboot", "--mode=default", "--wait", "--timeout=10m")])

    def test_partial_receipt_failure_cannot_submit_or_retry(self):
        plan = self.inspect()
        M.MAINTENANCE["save_inspection"](self.args.plan, plan)
        self.args.approve_plan_sha256 = M.digest(plan)
        save = M.MAINTENANCE["save_inspection"]
        def fail_after_creation(path, record):
            save(path, record)
            raise OSError("simulated directory fsync failure")
        with patch.dict(M.MAINTENANCE, {"save_inspection": fail_after_creation}), self.assertRaises(OSError):
            M.execute(self.args, self.read, self.directory)
        with self.assertRaisesRegex(ValueError, "attempt_already_consumed"):
            M.execute(self.args, self.read, self.directory)
        self.assertFalse(any("reboot" in command for command in self.read.commands))

    def test_changed_writer_or_approval_never_submits(self):
        plan = self.inspect()
        M.MAINTENANCE["save_inspection"](self.args.plan, plan)
        self.args.approve_plan_sha256 = "wrong"
        with self.assertRaisesRegex(ValueError, "approval"):
            M.execute(self.args, self.read, self.directory)
        self.args.approve_plan_sha256 = M.digest(plan)
        self.read.target["spec"]["containers"][0]["image"] = "changed"
        with self.assertRaisesRegex(ValueError, "evidence_changed"):
            M.execute(self.args, self.read, self.directory)
        self.assertFalse((self.directory / M.ATTEMPT).exists())

    def test_new_acer_consumer_at_submission_boundary_blocks(self):
        plan = self.inspect()
        M.MAINTENANCE["save_inspection"](self.args.plan, plan)
        self.args.approve_plan_sha256 = M.digest(plan)
        get = self.read.get
        calls = 0
        def changed(namespace, kind, *arguments):
            nonlocal calls
            if kind == "pods":
                calls += 1
                if calls == 2:
                    added = pod("unexpected", "ai", "acer", ref("ReplicaSet", "other", "other-uid"))
                    added["spec"]["containers"][0]["resources"]["requests"]["memory"] = "7Gi"
                    self.read.pods.append(added)
            return get(namespace, kind, *arguments)
        self.read.get = changed
        with self.assertRaisesRegex(ValueError, "last_moment_capacity_changed"):
            M.execute(self.args, self.read, self.directory)
        self.assertFalse((self.directory / M.ATTEMPT).exists())
        self.assertFalse(any("reboot" in command for command in self.read.commands))

    def test_second_registry_cannot_reset_attempt(self):
        with self.assertRaisesRegex(ValueError, "fixed_persistent_registry"):
            M.receipt_directory(self.directory)

    def test_unknown_owner_rejected_before_any_read(self):
        for kind, name in [("Secret", "sensitive"), ("DaemonSet", "--raw=/api"), ("Unknown", "anything")]:
            self.read.calls.clear()
            value = copy.deepcopy(self.read.target)
            value["metadata"]["ownerReferences"] = [ref(kind, name, "uid")]
            with self.assertRaises(ValueError):
                M.classify_pod(value, [value], self.read)
            self.assertEqual(self.read.calls, [])

    def test_all_container_class_and_persistent_writer_denials(self):
        for field in ["containers", "initContainers", "ephemeralContainers"]:
            value = copy.deepcopy(self.read.target)
            value["spec"][field] = [{"name": "writer", "volumeDevices": [{"name": "disk", "devicePath": "/dev/x"}]}]
            with self.subTest(field=field), self.assertRaises(ValueError):
                M.classify_pod(value, [value], self.read)
        for volume in [{"persistentVolumeClaim": {"claimName": "data"}}, {"hostPath": {"path": "/unexpected"}}, {"nfs": {"server": "fixture", "path": "/"}}]:
            value = copy.deepcopy(self.read.target)
            value["spec"]["volumes"] = [{"name": "data", **volume}]
            with self.subTest(volume=volume), self.assertRaises(ValueError):
                M.classify_pod(value, [value], self.read)

    def test_exact_propagation_allows_reviewed_init_but_no_other_mode(self):
        value = pod("multus", "kube-system", M.NODE, ref("DaemonSet", "kube-multus-ds", "multus-uid"))
        self.read.objects[("kube-system", "DaemonSet", "kube-multus-ds")] = obj("kube-multus-ds", "kube-system", "multus-uid")
        value["spec"]["volumes"] = [{"name": "cni", "hostPath": {"path": "/opt/cni/bin"}}]
        value["spec"]["initContainers"] = [{"name": "install-multus-binary", "volumeMounts": [{"name": "cni", "mountPath": "/host/opt/cni/bin", "mountPropagation": "Bidirectional"}]}]
        self.assertEqual(M.classify_pod(value, [value], self.read)["class"], "platform-daemon")
        value["spec"]["initContainers"][0]["volumeMounts"][0]["mountPath"] = "/wrong"
        with self.assertRaisesRegex(ValueError, "propagation"):
            M.classify_pod(value, [value], self.read)

    def test_stateful_identity_expansion_and_single_writer(self):
        name = "ts-bulldozer-hook-tccs6"
        value = pod(name + "-0", "tailscale", M.NODE, ref("StatefulSet", name, "sts-uid"))
        value["metadata"]["deletionTimestamp"] = stamp(-10)
        labels = {"tailscale.com/managed": "true", "tailscale.com/parent-resource": "bulldozer-hook", "tailscale.com/parent-resource-ns": "traefik", "tailscale.com/parent-resource-type": "ingress"}
        value["metadata"]["labels"] = labels
        value["spec"]["containers"] = [{"name": "tailscale", "image": M.TAILSCALE_IMAGE, "env": [
            {"name": "POD_NAME", "valueFrom": {"fieldRef": {"apiVersion": "v1", "fieldPath": "metadata.name"}}},
            {"name": "TS_KUBE_SECRET", "value": "$(POD_NAME)"}]}]
        control = obj(name, "tailscale", "sts-uid")
        control["metadata"]["labels"] = labels
        control["spec"] = {"replicas": 1, "podManagementPolicy": "OrderedReady", "updateStrategy": {"type": "RollingUpdate"}, "template": {"spec": copy.deepcopy(value["spec"])}}
        control["status"] = {"observedGeneration": 1, "currentRevision": "same", "updateRevision": "same"}
        self.read.objects[("tailscale", "StatefulSet", name)] = control
        self.read.objects[("traefik", "ingress", "bulldozer-hook")] = obj("bulldozer-hook", "traefik")
        self.assertEqual(M.classify_pod(value, [value], self.read)["identity_secret_uid"], "identity-uid")
        sibling = copy.deepcopy(value)
        sibling["metadata"]["uid"] = "second"
        with self.assertRaisesRegex(ValueError, "second_identity_writer"):
            M.classify_pod(value, [value, sibling], self.read)
        value["spec"]["containers"][0]["env"][0] = {"name": "POD_NAME", "value": "another-identity"}
        with self.assertRaisesRegex(ValueError, "identity_expansion"):
            M.classify_pod(value, [value], self.read)

    def test_stale_controller_available_count_is_not_replacement_proof(self):
        old = copy.deepcopy(self.read.gateway)
        old["metadata"]["uid"] = "old-target-pod"
        old["metadata"]["deletionTimestamp"] = stamp(-10)
        old["spec"]["nodeName"] = M.NODE
        self.read.objects[("ai", "ReplicaSet", "litellm-current")] = self.read.rs
        result = M.classify_pod(old, [old, self.read.gateway], self.read)
        self.assertEqual(result["replacement_pod_uids"], [self.read.gateway["metadata"]["uid"]])
        with self.assertRaisesRegex(ValueError, "replacement_pods_unavailable"):
            M.classify_pod(old, [old], self.read)
        self.read.gateway["metadata"]["deletionTimestamp"] = stamp(-1)
        with self.assertRaisesRegex(ValueError, "replacement_pods_unavailable"):
            M.classify_pod(old, [old, self.read.gateway], self.read)

    def test_extra_gateway_on_acer_is_not_hidden_from_capacity(self):
        extra = copy.deepcopy(self.read.gateway)
        extra["metadata"]["uid"] = "terminating-acer-gateway"
        extra["metadata"]["deletionTimestamp"] = stamp(-1)
        self.read.pods.append(extra)
        self.assertIn("prevention_and_capacity_unverified", self.inspect()["blockers"])

    def test_read_only_verify_requires_new_boot_and_fresh_ready(self):
        self.assertIn("identity_unverified", M.inspect(self.args, self.read, recovered=True)["blockers"])
        self.read.boot = "new-boot"
        self.read.recovered = True
        self.read.nodes[-1]["status"]["nodeInfo"]["bootID"] = "new-boot"
        self.read.nodes[-1]["status"]["conditions"][0]["status"] = "True"
        self.read.leases[-1]["spec"]["renewTime"] = stamp(-1)
        self.assertEqual(M.inspect(self.args, self.read, recovered=True)["blockers"], [])
        self.assertFalse(any("reboot" in command for command in self.read.commands))

    def test_stale_or_raced_plan_cannot_submit(self):
        plan = self.inspect()
        plan["observed_at"] = stamp(-301)
        M.MAINTENANCE["save_inspection"](self.args.plan, plan)
        self.args.approve_plan_sha256 = M.digest(plan)
        with self.assertRaisesRegex(ValueError, "stale_or_future"):
            M.execute(self.args, self.read, self.directory)
        self.assertFalse((self.directory / M.ATTEMPT).exists())

    def test_native_proxy_requests_metadata_and_rejects_full_secret_fallback(self):
        accepted = []
        response = {"kind": "PartialObjectMetadata", "apiVersion": "meta.k8s.io/v1", "metadata": {
            "name": "fixture", "namespace": "tailscale", "uid": "00000000-0000-0000-0000-000000000001"}}
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(handler):
                accepted.append((handler.path, handler.headers.get("Accept")))
                content = json.dumps(response).encode()
                handler.send_response(200)
                handler.send_header("Content-Type", "application/json")
                handler.send_header("Content-Length", str(len(content)))
                handler.end_headers()
                handler.wfile.write(content)
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # Public synthetic credentials-free API only; bypass constructor's
            # production endpoint check solely to exercise real kubectl proxy.
            config = self.directory / "fixture-kubeconfig.json"
            config.write_text(json.dumps({"apiVersion": "v1", "kind": "Config", "current-context": "fixture",
                "contexts": [{"name": "fixture", "context": {"cluster": "fixture", "user": "fixture"}}],
                "clusters": [{"name": "fixture", "cluster": {"server": f"http://127.0.0.1:{server.server_port}"}}],
                "users": [{"name": "fixture", "user": {}}]}))
            reader = M.Reader.__new__(M.Reader)
            reader.env = {key: value for key, value in os.environ.items() if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}}
            reader.kube = ["kubectl", "--kubeconfig", str(config), "--context", "fixture", "--request-timeout=15s"]
            proxies = []
            popen = M.subprocess.Popen
            def tracked(command, **kwargs):
                process = popen(command, **kwargs)
                proxies.append((process, Path(command[command.index("--unix-socket") + 1])))
                return process
            with patch.object(M.subprocess, "Popen", side_effect=tracked):
                self.assertEqual(reader.secret_uid("fixture"), response["metadata"]["uid"])
                response.update(kind="Secret", apiVersion="v1", data={"fixture": "synthetic-never-private"})
                with self.assertRaisesRegex(ValueError, "full_secret_response_rejected"):
                    reader.secret_uid("fixture")
            for process, endpoint in proxies:
                self.assertIsNotNone(process.poll())
                self.assertFalse(endpoint.parent.exists())
            self.assertEqual(accepted, [("/api/v1/namespaces/tailscale/secrets/fixture",
                "application/json;as=PartialObjectMetadata;g=meta.k8s.io;v=v1")] * 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_explicit_talos_client_version_hash_and_no_path_selection(self):
        binary = self.directory / "talosctl"
        binary.write_text("synthetic executable v1")
        binary.chmod(0o700)
        calls = []
        def version(command):
            calls.append(command)
            return "Client:\n\tTag: v1.11.3\n\tSHA: fixture\n"
        record = M.talos_client(binary, version)
        self.assertEqual(calls, [[str(binary.resolve()), "version", "--client"]])
        reader = M.Reader.__new__(M.Reader)
        reader.client = record
        reader.args = SimpleNamespace(talosconfig=Path("/synthetic/private-config"))
        reader.run = lambda command, timeout=25: calls.append(command)
        with patch.dict(os.environ, {"PATH": "/must-not-select-client"}):
            reader.talos(M.ADDRESS, "get", "services")
        self.assertEqual(calls[-1][0], str(binary.resolve()))
        binary.write_text("replaced executable v2")
        with self.assertRaisesRegex(ValueError, "approved_talos_client_changed"):
            reader.talos(M.ADDRESS, "get", "services")
        for value in ("Client:\n Tag: v1.13.2\n", "Client:\n Tag: v1.11.30\n", "no version", "Tag: v1.11.3\nTag: v1.11.3\n"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "matched_talos"):
                M.talos_client(binary, lambda command: value)
        with self.assertRaisesRegex(ValueError, "absolute_talos"):
            M.talos_client(Path("talosctl"), version)
        binary.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "not_executable"):
            M.talos_client(binary, version)

    def test_different_same_version_client_rejects_approved_plan(self):
        plan = self.inspect()
        M.MAINTENANCE["save_inspection"](self.args.plan, plan)
        self.args.approve_plan_sha256 = M.digest(plan)
        self.read.client = {**self.read.client, "sha256": "b" * 64}
        with self.assertRaisesRegex(ValueError, "approved_evidence_changed"):
            M.execute(self.args, self.read, self.directory)
        self.assertFalse((self.directory / M.ATTEMPT).exists())
        self.assertFalse(any("reboot" in command for command in self.read.commands))

    def test_reviewed_main_and_private_configuration_guard(self):
        kube, talos = self.directory / "kubeconfig", self.directory / "talosconfig"
        for path in (kube, talos):
            path.write_text("synthetic")
            path.chmod(0o600)
        args = SimpleNamespace(reviewed_sha="a" * 40, kubeconfig=kube, talosconfig=talos)
        with patch.object(M.subprocess, "check_output", side_effect=["a" * 40, "a" * 40, b""]):
            M.source_guard(args)
        for output in [["b" * 40], ["a" * 40, "b" * 40], ["a" * 40, "a" * 40, b" M changed"]]:
            with patch.object(M.subprocess, "check_output", side_effect=output), self.assertRaises(ValueError):
                M.source_guard(args)
        kube.chmod(0o644)
        with patch.object(M.subprocess, "check_output", side_effect=["a" * 40, "a" * 40, b""]), self.assertRaisesRegex(ValueError, "private_config"):
            M.source_guard(args)

    def test_direct_endpoint_and_no_exec_or_proxy(self):
        valid = {"current-context": "direct", "contexts": [{"name": "direct", "context": {"cluster": "homelab", "user": "owner"}}],
                 "clusters": [{"name": "homelab", "cluster": {"server": "https://10.1.0.199:6443", "certificate-authority-data": "REDACTED"}}],
                 "users": [{"name": "owner", "user": {"client-certificate-data": "REDACTED", "client-key-data": "REDACTED"}}]}
        M.validate_kubeconfig(valid, "direct")
        for field, value in [("server", "https://elsewhere"), ("proxy-url", "https://proxy"), ("insecure-skip-tls-verify", True), ("tls-server-name", "override")]:
            invalid = copy.deepcopy(valid)
            invalid["clusters"][0]["cluster"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                M.validate_kubeconfig(invalid, "direct")
        valid["users"][0]["user"] = {"exec": {"command": "must-never-run"}}
        with self.assertRaises(ValueError):
            M.validate_kubeconfig(valid, "direct")


if __name__ == "__main__":
    unittest.main()
