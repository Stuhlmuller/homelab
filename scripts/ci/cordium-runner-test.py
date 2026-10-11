#!/usr/bin/env python3
"""Exercise one-job credential handling and independent cleanup without live APIs."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("runner", Path(__file__).resolve().parents[1] / "cordium-runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
SHA = "a" * 40
JIT = "cHJpdmF0ZS1qaXQtZml4dHVyZQ=="
UID = "11111111-2222-3333-4444-555555555555"


class Lifecycle(unittest.TestCase):
    def exercise(self, *, failure=False, wrong_sha=False, retained=False, cleanup_fails=False, invalid_name=False, invalid_jit=False,
                 invalid_uid=False, policy_mismatch=False, backend_missing=False, pod_retained=False, deployment_retained=False, pvc_retained=False,
                 wrong_context=False, enforcer_unready=False, conflicting_backend=False, wrong_node=False, mounted_token=False, host_namespace=False):
        calls = []
        api_calls = []
        present = [True]
        lists = [0]
        events = []
        policy = [None]
        deleted = [False]
        clock = [0]

        def command(arguments, **kwargs):
            args = arguments[5:]
            calls.append((args, kwargs))
            events.append(args[0])
            output = b""
            if args[:2] == ["get", "workspace"] and args[2] == "--out":
                lists[0] += 1
                output = json.dumps({"items": [{"metadata": {"name": "old"}}] if retained and lists[0] == 1 else []}).encode()
            elif args[:2] == ["create", "workspace"]:
                output = json.dumps({"metadata": {"name": "--all" if invalid_name else "abc", "uid": "bad" if invalid_uid else UID}}).encode()
            elif args[0] == "get":
                output = b'{"status":{"state":"RUNNING"}}'
            elif "rev-parse" in args:
                output = ("b" * 40 if wrong_sha else SHA).encode()
            elif args[0] == "exec":
                self.assertEqual(kwargs["input"], JIT.encode())
                self.assertNotIn(JIT, args)
                self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
                self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
                if failure:
                    raise subprocess.CalledProcessError(17, arguments)
            elif args[0] == "delete":
                if cleanup_fails:
                    raise subprocess.CalledProcessError(1, arguments)
                deleted[0] = True
            return subprocess.CompletedProcess(arguments, 0, output, b"")

        def kube(*args, input=None):
            events.append("kube-" + args[0])
            if args[0] == "config":
                return b"https://other-cluster.invalid" if wrong_context else b"https://10.1.0.199:6443"
            enforcer = {"containers": [{"image": "registry.k8s.io/networking/kube-network-policies@sha256:c671f98e444825d57c590c92da1b5e66070917c4d3dff1f9279775e6b73254fe",
                                       "args": ["--fail-open=false", "--strict-mode=true", "--disable-nri=false"]}]}
            if conflicting_backend:
                enforcer["containers"][0]["args"].append("--disable-nri=true")
            if args[1] == "daemonset":
                if backend_missing:
                    raise RuntimeError("Missing policy enforcer")
                return json.dumps({"metadata": {"generation": 1}, "status": {"observedGeneration": 1, "desiredNumberScheduled": 1, "numberReady": 0 if enforcer_unready else 1}, "spec": {"template": {"spec": enforcer}}}).encode()
            if args[1] == "pods" and "kube-system" in args:
                return json.dumps({"items": [{"spec": enforcer, "status": {"conditions": [{"type": "Ready", "status": "True"}]}}]}).encode()
            if args[0] == "create":
                policy[0] = json.loads(input)
                if policy_mismatch:
                    policy[0]["spec"]["egress"] = []
                return json.dumps(policy[0]).encode()
            if args[1] == "networkpolicy":
                if args[0] == "delete":
                    policy[0] = None
                    return b""
                return json.dumps(policy[0]).encode() if policy[0] else b""
            if args[1] == "pods":
                if deleted[0] and not pod_retained:
                    return b'{"items":[]}'
                return json.dumps({"items": [{"spec": {"nodeName": "other-worker" if wrong_node else "zimaboard-1", "automountServiceAccountToken": mounted_token, "hostNetwork": host_namespace}}]}).encode()
            if args[1] == "persistentvolumeclaim":
                self.assertEqual(args[2], "ws-" + UID)
                return b'{}' if pvc_retained else b""
            if args[1] == "deployment":
                self.assertEqual(args[2], "ws-abc")
                return b'{}' if deployment_retained else b""
            raise AssertionError(args)

        def monotonic():
            clock[0] += 10
            return clock[0]

        def api(method, path, body=None):
            api_calls.append((method, path, body))
            if method == "POST":
                self.assertEqual(body["labels"], ["self-hosted", "Linux", "X64", "cordium-canary"])
                return {"runner": {"id": 23, "name": "cordium-abc"}, "encoded_jit_config": "invalid secret!" if invalid_jit else JIT}
            if method == "DELETE":
                present[0] = False
                return None
            if present[0]:
                return {"id": 23}
            raise RuntimeError("GitHub request failed with HTTP 404; response withheld")

        output = io.StringIO()
        error = None
        with patch.object(runner.subprocess, "run", side_effect=command), patch.object(runner, "kube", side_effect=kube), \
             patch.object(runner.time, "monotonic", side_effect=monotonic), patch.object(runner.time, "sleep"), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                runner.provision(api, ["cordium", "--homedir", "/private/fixture", "--domain", "stinkyboi.com"], SHA)
            except (RuntimeError, subprocess.CalledProcessError) as caught:
                error = caught
        self.assertNotIn(JIT, output.getvalue())
        self.events = events
        self.policy_retained = policy[0] is not None
        return error, calls, api_calls

    def test_one_job_receives_only_jit_stdin_then_disposes_workspace_and_runner(self):
        error, calls, api_calls = self.exercise()
        self.assertIsNone(error)
        self.assertIn(["delete", "workspace", "abc"], [args for args, _ in calls])
        self.assertIn(("DELETE", "/repos/Stuhlmuller/homelab/actions/runners/23", None), api_calls)
        self.assertLess(self.events.index("kube-create"), self.events.index("start"))
        self.assertGreater(self.events.index("kube-delete"), self.events.index("delete"))
        self.assertFalse(self.policy_retained)

    def test_missing_backend_invalid_uid_or_mismatched_policy_never_starts_runner(self):
        for options in ({"backend_missing": True}, {"wrong_context": True}, {"enforcer_unready": True}, {"conflicting_backend": True},
                        {"invalid_uid": True}, {"policy_mismatch": True}):
            error, calls, api_calls = self.exercise(**options)
            self.assertIsNotNone(error)
            self.assertEqual(api_calls, [])
            self.assertFalse(any(args[0] == "start" for args, _ in calls))

    def test_unsafe_pod_never_receives_runner_credentials(self):
        for options in ({"wrong_node": True}, {"mounted_token": True}, {"host_namespace": True}):
            error, calls, api_calls = self.exercise(**options)
            self.assertIsNotNone(error)
            self.assertEqual(api_calls, [])
            self.assertIn(["delete", "workspace", "abc"], [args for args, _ in calls])

    def test_retained_pod_keeps_isolation_and_still_unregisters_runner(self):
        for options in ({"pod_retained": True}, {"deployment_retained": True}, {"pvc_retained": True}):
            error, _, api_calls = self.exercise(**options)
            self.assertIsNotNone(error)
            self.assertTrue(self.policy_retained)
            self.assertNotIn("kube-delete", self.events)
            self.assertIn(("DELETE", "/repos/Stuhlmuller/homelab/actions/runners/23", None), api_calls)

    def test_conflicting_backend_flags_are_not_accepted(self):
        config = {"containers": [{"image": "mirror/policy@sha256:c671f98e444825d57c590c92da1b5e66070917c4d3dff1f9279775e6b73254fe", "args": ["--fail-open=false", "--strict-mode=true", "--disable-nri=false", "--fail-open=true"]}]}
        self.assertFalse(runner.enforcer_config(config))

    def test_failure_and_invalid_jit_still_clean_both_resources(self):
        for options in ({"failure": True}, {"invalid_jit": True}, {"cleanup_fails": True}):
            error, calls, api_calls = self.exercise(**options)
            self.assertIsNotNone(error)
            self.assertIn(["delete", "workspace", "abc"], [args for args, _ in calls])
            self.assertIn(("DELETE", "/repos/Stuhlmuller/homelab/actions/runners/23", None), api_calls)

    def test_wrong_checkout_or_retained_inventory_prevents_registration(self):
        for options in ({"wrong_sha": True}, {"retained": True}, {"invalid_name": True}):
            error, calls, api_calls = self.exercise(**options)
            self.assertIsNotNone(error)
            self.assertEqual(api_calls, [])
            if not options.get("wrong_sha"):
                self.assertFalse(any(args[0] == "delete" for args, _ in calls))

    def test_only_exact_runner_404_is_absence(self):
        with self.assertRaises(RuntimeError):
            runner.runner_present(Mock(side_effect=RuntimeError("GitHub request failed with HTTP 403; response withheld")), "Stuhlmuller/homelab", 23)

    def test_shared_github_client_accepts_empty_delete_response(self):
        response = io.BytesIO()
        response.status = 204
        opener = Mock()
        opener.open.return_value = response
        with patch.object(runner.github_operator.urllib.request, "build_opener", return_value=opener):
            self.assertIsNone(runner.github_operator.github_client("fixture")("DELETE", "/repos/Stuhlmuller/homelab/actions/runners/23"))

    def test_disabled_pool_rejects_before_reading_key_or_opening_clients(self):
        with patch.object(sys, "argv", ["runner", "--expected-sha", SHA, "--app-key-file", "/missing/key", "--homedir", "/missing/login"]), \
             patch.object(runner.github_operator, "verify_reviewed_main"), \
             patch.object(runner.github_operator, "command", return_value=b""), \
             patch.object(runner.github_operator, "app_jwt") as signer, \
             self.assertRaisesRegex(RuntimeError, "registration is disabled"):
            runner.main()
        signer.assert_not_called()

    def test_human_agent_wrong_domain_or_policy_login_rejected_before_app_key(self):
        pool = json.loads((runner.ROOT / ".cordium/runner-pool.json").read_text())
        pool["enabled"] = True
        good = {"domain": "stinkyboi.com", "user": {"metadata": {"name": "homelab-cordium-runners"},
                "spec": {"type": "WORKLOAD", "authorization": {"policies": ["homelab-cordium-runner-execution"]}}}}
        cases = []
        for name in ("homelab-cordium-user", "homelab-cordium-agent", "homelab-cordium-ci"):
            status = copy.deepcopy(good)
            status["user"]["metadata"]["name"] = name
            cases.append(status)
        status = copy.deepcopy(good)
        status["domain"] = "other.invalid"
        cases.append(status)
        status = copy.deepcopy(good)
        status["user"]["spec"]["type"] = "HUMAN"
        cases.append(status)
        status = copy.deepcopy(good)
        status["user"]["spec"]["authorization"]["policies"].append("bootstrap-access")
        cases.append(status)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".cordium").mkdir()
            (root / ".cordium/runner-pool.json").write_text(json.dumps(pool))
            for status in cases:
                with patch.object(runner, "ROOT", root), \
                     patch.object(sys, "argv", ["runner", "--expected-sha", SHA, "--app-key-file", "/missing/key", "--homedir", "/missing/login"]), \
                     patch.object(runner.github_operator, "verify_reviewed_main"), \
                     patch.object(runner.github_operator, "command", side_effect=[b"", b"gitCommit: e12b0b16d5fe94716e414fca7cfdc10b21014f2c\n", json.dumps(status).encode()]), \
                     patch.object(runner.github_operator, "app_jwt") as signer, \
                     self.assertRaisesRegex(RuntimeError, "dedicated policy-bound runner identity"):
                    runner.main()
                signer.assert_not_called()


class Queue(unittest.TestCase):
    def setUp(self):
        self.pool = json.loads((runner.ROOT / ".cordium/runner-pool.json").read_text())

    def test_pending_jobs_in_active_runs_match_all_labels_case_insensitively(self):
        def api(method, path):
            if "status=in_progress" in path:
                return {"workflow_runs": [{"id": 7}]}
            if "/jobs?" in path:
                return {"jobs": [{"status": "queued", "labels": ["SELF-HOSTED", "linux", "x64", "cordium-canary"]}]}
            return {"workflow_runs": []}
        self.assertTrue(runner.queued_jobs(api, self.pool))

    def test_hosted_wrong_pool_and_finished_jobs_do_not_provision(self):
        for job in ({"status": "queued", "labels": ["ubuntu-24.04"]},
                    {"status": "queued", "labels": ["self-hosted", "cordium"]},
                    {"status": "completed", "labels": self.pool["labels"]}):
            def api(method, path):
                if "/jobs?" in path:
                    return {"jobs": [job]}
                return {"workflow_runs": [{"id": 7}]} if "status=queued" in path else {"workflow_runs": []}
            self.assertFalse(runner.queued_jobs(api, self.pool))

    def test_both_run_and_job_pagination_are_complete(self):
        calls = []
        def api(method, path):
            calls.append(path)
            page = parse_qs(urlparse(path).query)["page"][0]
            if "/jobs?" in path:
                if "/101/jobs?" in path:
                    if page == "1":
                        return {"jobs": [{"status": "completed", "labels": []}] * 100}
                    return {"jobs": [{"status": "queued", "labels": self.pool["labels"]}]}
                return {"jobs": []}
            if "status=queued" in path:
                return {"workflow_runs": [{"id": i} for i in range(1, 101)]} if page == "1" else {"workflow_runs": [{"id": 101}]}
            return {"workflow_runs": []}
        self.assertTrue(runner.queued_jobs(api, self.pool))
        self.assertTrue(any("status=queued" in path and "page=2" in path for path in calls))
        self.assertTrue(any("/101/jobs?" in path and "page=2" in path for path in calls))

    def test_loop_refreshes_client_and_stops_on_lifecycle_or_main_failure(self):
        with patch.object(runner.github_operator, "verify_reviewed_main") as guard, \
             patch.object(runner, "native_identity"), \
             patch.object(runner, "installation_client", return_value="private-api") as client, \
             patch.object(runner, "queued_jobs", return_value=True), \
             patch.object(runner, "provision", side_effect=RuntimeError("cleanup incomplete")) as provision, \
             patch.object(runner.time, "sleep") as sleep:
            with self.assertRaises(RuntimeError):
                runner.serve(self.pool, Path("/private/key"), ["cordium"], SHA)
            guard.assert_called_once_with(SHA)
            client.assert_called_once()
            provision.assert_called_once()
            sleep.assert_not_called()
        with patch.object(runner.github_operator, "verify_reviewed_main", side_effect=RuntimeError("main changed")), \
             patch.object(runner, "installation_client") as client:
            with self.assertRaises(RuntimeError):
                runner.serve(self.pool, Path("/private/key"), ["cordium"], SHA)
            client.assert_not_called()

    def test_filtered_search_cap_and_native_failure_do_not_create_runners(self):
        with self.assertRaises(RuntimeError):
            runner.queued_jobs(Mock(return_value={"total_count": 1000, "workflow_runs": []}), self.pool)
        with patch.object(runner.github_operator, "verify_reviewed_main"), \
             patch.object(runner, "native_identity", side_effect=RuntimeError("session unavailable")), \
             patch.object(runner, "installation_client") as client:
            with self.assertRaises(RuntimeError):
                runner.serve(self.pool, Path("/private/key"), ["cordium"], SHA)
            client.assert_not_called()

    def test_idle_poll_refreshes_scoped_client_without_provisioning(self):
        with patch.object(runner.github_operator, "verify_reviewed_main"), \
             patch.object(runner, "native_identity"), \
             patch.object(runner, "installation_client", return_value="private-api") as client, \
             patch.object(runner, "queued_jobs", return_value=False), \
             patch.object(runner, "provision") as provision, \
             patch.object(runner.time, "sleep", side_effect=[None, SystemExit(0)]):
            with self.assertRaises(SystemExit):
                runner.serve(self.pool, Path("/private/key"), ["cordium"], SHA)
            self.assertEqual(client.call_count, 2)
            provision.assert_not_called()


if __name__ == "__main__":
    unittest.main()
