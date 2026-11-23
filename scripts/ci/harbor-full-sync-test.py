#!/usr/bin/env python3
"""Exercise fixed-scope Harbor recovery without cluster or Git mutations."""
import contextlib
import copy
import importlib.util
import io
import json
import os
import signal
from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


RECOVER = module("harbor_recovery", ROOT / "scripts/harbor-full-sync.py")
FIXTURE = module("gitops_fixtures", ROOT / "scripts/ci/verify-gitops-test.py")
SHA = FIXTURE.SHA
IMAGE = "harbor.stinkyboi.com/homelab/homelab-harbor-core:homelab-" + SHA + "@" + FIXTURE.DIGEST
ENDPOINT = "127.0.0.1:45678"


class Cluster:
    def __init__(self):
        self.app = FIXTURE.fixtures(True)[0]
        self.app["metadata"] = FIXTURE.metadata("harbor", "argocd", 1)
        self.app["spec"] = {"sources": copy.deepcopy(RECOVER.SOURCES), "project": "homelab",
                            "destination": {"server": "https://kubernetes.default.svc", "namespace": "harbor"}}
        self.app["status"]["sync"] = {
            "status": "Synced", "revisions": [RECOVER.CHART, SHA, SHA],
            "comparedTo": {"sources": copy.deepcopy(RECOVER.SOURCES),
                           "destination": copy.deepcopy(self.app["spec"]["destination"])},
        }
        self.app["status"]["operationState"] = {
            "phase": "Failed", "startedAt": "2026-11-18T00:00:00Z", "finishedAt": "2026-11-18T00:15:00Z",
            "message": "Operation terminated, triggered by controller sync timeout",
            "syncResult": {"sources": copy.deepcopy(RECOVER.SOURCES),
                           "revisions": [RECOVER.CHART, SHA, SHA]},
        }
        self.app["status"]["resources"] = [
            {"group": "apps", "kind": "Deployment", "namespace": "harbor", "name": target.split("/")[1],
             "status": "Synced"} for target in RECOVER.DEPLOYMENTS]
        self.resources = {}
        for index, target in enumerate(RECOVER.DEPLOYMENTS, 1):
            name = target.split("/")[1]
            _, deployment, rs, pod = FIXTURE.fixtures()
            deployment["metadata"] = {**FIXTURE.metadata(name, "harbor", index * 10),
                                       "annotations": {FIXTURE.REVISION: "2"}}
            deployment["spec"]["selector"] = {"matchLabels": {"app": name}}
            container = "core" if index == 1 else "exporter"
            image = IMAGE if index == 1 else "example.invalid/exporter@" + FIXTURE.DIGEST
            deployment["spec"]["template"]["spec"]["containers"] = [{"name": container, "image": image}]
            rs["metadata"] = {**FIXTURE.metadata(name + "-rs", "harbor", index * 10 + 1),
                               "annotations": {FIXTURE.REVISION: "2"},
                               "ownerReferences": FIXTURE.owner("Deployment", deployment)}
            rs["spec"]["template"] = copy.deepcopy(deployment["spec"]["template"])
            pod["metadata"] = {**FIXTURE.metadata(name + "-pod", "harbor", index * 10 + 2),
                                "ownerReferences": FIXTURE.owner("ReplicaSet", rs)}
            pod["spec"] = copy.deepcopy(rs["spec"]["template"]["spec"])
            pod["status"]["containerStatuses"] = [
                {"name": container, "ready": True, "state": {"running": {}}, "imageID": image}]
            self.resources[name] = {"deployment": deployment, "replicasets": rs, "pods": pod}

    def read(self, namespace, kind, *arguments):
        if kind == "application":
            assert namespace == "argocd" and arguments == ("harbor",)
            return copy.deepcopy(self.app)
        assert namespace == "harbor"
        name = arguments[0] if kind == "deployment" else arguments[1].removeprefix("app=")
        item = copy.deepcopy(self.resources[name][kind])
        return item if kind == "deployment" else {"kind": item["kind"] + "List", "items": [item]}

    def succeed(self):
        operation = self.app["status"]["operationState"]
        operation.update(phase="Succeeded", startedAt="2026-11-18T01:00:00Z", finishedAt="2026-11-18T01:10:00Z")
        operation["syncResult"]["resources"] = [
            {"group": "batch", "kind": "Job", "namespace": "harbor", "name": name, "hookType": "PostSync",
             "syncPhase": "PostSync", "hookPhase": "Succeeded"} for name in sorted(RECOVER.HOOKS)]


class Commands:
    def __init__(self, cluster):
        self.cluster = cluster
        self.calls = []
        self.dirty = ""
        self.head = SHA
        self.remote = SHA
        self.image = IMAGE
        self.contexts = {"operator": {"cluster": "homelab", "user": "admin", "namespace": "default"}}
        self.current_context = "operator"
        self.fail_sync = False
        self.interrupt_sync = False

    def __call__(self, *args, timeout=30):
        self.calls.append((args, timeout))
        if args[:3] == ("git", "status", "--porcelain=v1"):
            return self.dirty
        if args == ("git", "rev-parse", "HEAD"):
            return self.head + "\n"
        if args == ("git", "ls-remote", RECOVER.REPOSITORY, "refs/heads/main"):
            return self.remote + "\trefs/heads/main\n"
        if args == ("yq", "-o=json", ".core.image", "clusters/homelab/apps/harbor/values.yaml"):
            repository, tag = self.image.split(":", 1)
            return json.dumps({"repository": repository, "tag": tag})
        if args == ("kubectl", "config", "view", "--minify", "-o", "json"):
            return json.dumps({"current-context": self.current_context,
                               "contexts": [{"name": self.current_context,
                                             "context": self.contexts[self.current_context]}]})
        if args[:4] == ("argocd", "app", "get", "harbor"):
            app = copy.deepcopy(self.cluster.app)
            app.pop("kind", None)
            app.pop("apiVersion", None)
            return json.dumps(app)
        if args[:4] == ("argocd", "app", "sync", "harbor"):
            if self.interrupt_sync:
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            if self.fail_sync:
                raise subprocess.CalledProcessError(1, args, stderr="private-credential")
            self.cluster.succeed()
            return ""
        if args[:4] == ("argocd", "app", "wait", "harbor"):
            return ""
        raise AssertionError(args)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.cluster = Cluster()
        self.commands = Commands(self.cluster)
        self.process = MagicMock(pid=12345)
        self.process.poll.return_value = None
        self.startup_log = "Argo CD UI is available at http://" + ENDPOINT + "\n"
        self.socket = MagicMock()
        self.socket.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 45678)
        self.popen = MagicMock(side_effect=self.start_server)
        self.killpg = MagicMock()
        self.config = None
        self.patches = [patch.object(RECOVER, "run", self.commands),
                        patch.object(RECOVER, "read", self.cluster.read),
                        patch.object(RECOVER.socket, "socket", return_value=self.socket),
                        patch.object(RECOVER.subprocess, "Popen", self.popen),
                        patch.object(RECOVER.os, "killpg", self.killpg)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def start_server(self, args, **kwargs):
        self.config = args[-1]
        self.assertEqual(args, ["argocd", "admin", "dashboard", "--namespace", "argocd",
                               "--context", "operator", "--address", "127.0.0.1",
                               "--port", "45678", "--config", self.config])
        self.assertTrue(kwargs["start_new_session"])
        # Child stdout must append even after the parent seeks for readiness.
        output = kwargs["stdout"]
        output.write("startup\n")
        output.flush()
        output.seek(0)
        os.write(output.fileno(), b"child log\n")
        output.seek(0)
        self.assertEqual(output.read(), "startup\nchild log\n")
        self.assertFalse(Path(self.config).exists())
        kwargs["stdout"].write(self.startup_log)
        kwargs["stdout"].flush()
        return self.process

    def test_preview_has_no_argocd_mutation(self):
        self.assertEqual(RECOVER.recover(SHA), {"ready": True, "executed": False, "expected_sha": SHA})
        self.assertFalse(any(args[0] == "argocd" for args, _ in self.commands.calls))

    def test_execute_pins_every_source_and_verifies_hooks(self):
        result = RECOVER.recover(SHA, True)
        self.assertTrue(result["controller_verified"])
        self.assertTrue(result["postsync_hooks_verified"])
        self.killpg.assert_called_once_with(12345, signal.SIGTERM)
        self.process.wait.assert_called_once_with(timeout=10)
        self.assertFalse(Path(self.config).parent.exists())
        actual = [(args, timeout) for args, timeout in self.commands.calls if args[0] == "argocd"]
        flags = ("--server", ENDPOINT, "--plaintext", "--config", self.config)
        self.assertEqual(actual, [
            (("argocd", "app", "get", "harbor", *flags, "-o", "json"), 30),
            (("argocd", "app", "sync", "harbor", *flags,
              "--revisions", RECOVER.CHART,
              "--source-positions", "1", "--revisions", SHA, "--source-positions", "2",
              "--revisions", SHA, "--source-positions", "3", "--timeout", "900"), 930),
            (("argocd", "app", "wait", "harbor", *flags,
              "--sync", "--health", "--operation",
              "--timeout", "900"), 930),
        ])
        self.assertEqual(sum(args == ("git", "rev-parse", "HEAD") for args, _ in self.commands.calls), 3)
        self.assertEqual(self.commands.current_context, "operator")
        self.assertEqual(self.commands.contexts,
                         {"operator": {"cluster": "homelab", "user": "admin", "namespace": "default"}})

    def test_transport_rpc_identity_rejects_wrong_or_deleting_application(self):
        original = self.commands
        for change in (lambda app: app["metadata"].update(name="other"),
                       lambda app: app["metadata"].update(namespace="default"),
                       lambda app: app["metadata"].update(deletionTimestamp="2026-11-18T00:00:00Z"),
                       lambda app: app.update(kind="Secret")):
            def wrong_identity(*args, **kwargs):
                result = original(*args, **kwargs)
                if args[:3] == ("argocd", "app", "get"):
                    app = json.loads(result)
                    change(app)
                    return json.dumps(app)
                return result
            with patch.object(RECOVER, "run", wrong_identity):
                with self.assertRaisesRegex(RECOVER.Failure, "argocd_application_identity"):
                    RECOVER.recover(SHA, True)
        self.assertFalse(any(args[:3] == ("argocd", "app", "sync") for args, _ in self.commands.calls))
        self.assertEqual(self.killpg.call_count, 4)

    def test_transport_application_uid_must_match_preflight(self):
        original = self.commands
        def wrong_application(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[:3] == ("argocd", "app", "get"):
                app = json.loads(result)
                app["metadata"]["uid"] = "00000000-0000-4000-8000-000000000099"
                return json.dumps(app)
            return result
        with patch.object(RECOVER, "run", wrong_application):
            with self.assertRaisesRegex(RECOVER.Failure, "argocd_application_uid"):
                RECOVER.recover(SHA, True)
        self.assertFalse(any(args[:3] == ("argocd", "app", "sync") for args, _ in self.commands.calls))
        self.killpg.assert_called_once_with(12345, signal.SIGTERM)
        self.process.wait.assert_called_once_with(timeout=10)
        self.assertFalse(Path(self.config).parent.exists())

    def test_readiness_failure_never_requests_sync_and_cleans_server(self):
        original = self.commands
        def failed_get(*args, **kwargs):
            if args[:3] == ("argocd", "app", "get"):
                raise subprocess.CalledProcessError(1, args, stderr="private-credential")
            return original(*args, **kwargs)
        with patch.object(RECOVER, "run", failed_get):
            with self.assertRaises(subprocess.CalledProcessError):
                RECOVER.recover(SHA, True)
        self.killpg.assert_called_once_with(12345, signal.SIGTERM)
        self.assertFalse(any(args[:3] == ("argocd", "app", "sync") for args, _ in self.commands.calls))

    def test_server_cleanup_on_sync_failure(self):
        self.commands.fail_sync = True
        with self.assertRaises(subprocess.CalledProcessError):
            RECOVER.recover(SHA, True)
        self.killpg.assert_called_once_with(12345, signal.SIGTERM)
        self.process.wait.assert_called_once_with(timeout=10)
        self.assertFalse(Path(self.config).parent.exists())

    def test_server_fails_closed_for_exit_wrong_endpoint_timeout_and_bind_failure(self):
        for mode in ("exit", "endpoint", "timeout", "bind"):
            with self.subTest(mode=mode):
                self.process.poll.return_value = 1 if mode == "exit" else None
                self.startup_log = "Argo CD UI is available at http://0.0.0.0:45678\n" if mode == "endpoint" else ""
                self.socket.__enter__.return_value.bind.side_effect = OSError("bind failed") if mode == "bind" else None
                with patch.object(RECOVER.time, "monotonic", side_effect=[0, 91] if mode == "timeout" else [0, 1]):
                    with self.assertRaises((RECOVER.Failure, OSError)):
                        RECOVER.recover(SHA, True)
                self.assertFalse(any(args[:3] == ("argocd", "app", "sync") for args, _ in self.commands.calls))

    def test_server_escalates_cleanup_and_accepts_already_exited_group(self):
        self.process.wait.side_effect = [subprocess.TimeoutExpired("argocd", 10), 0]
        RECOVER.recover(SHA, True)
        self.assertEqual([call.args for call in self.killpg.call_args_list],
                         [(12345, signal.SIGTERM), (12345, signal.SIGKILL)])
        self.cluster = Cluster()
        self.commands.cluster = self.cluster
        with patch.object(RECOVER, "read", self.cluster.read):
            self.process.wait.side_effect = None
            self.killpg.side_effect = ProcessLookupError
            RECOVER.recover(SHA, True)

    def test_dirty_or_wrong_checkout_and_remote_fail_before_sync(self):
        for name, value in [("dirty", "?? secret\n"), ("head", "b" * 40), ("remote", "b" * 40)]:
            with self.subTest(name=name):
                original = getattr(self.commands, name)
                setattr(self.commands, name, value)
                with self.assertRaises(RECOVER.Failure):
                    RECOVER.recover(SHA, True)
                setattr(self.commands, name, original)
        self.assertFalse(any(args[0] == "argocd" for args, _ in self.commands.calls))

    def test_negative_live_preconditions_fail_before_sync(self):
        original = copy.deepcopy(self.cluster.app)
        changes = [
            lambda app: app.update(operation={"sync": {}}),
            lambda app: app["spec"]["sources"][0].update(targetRevision="1.19.3"),
            lambda app: app["spec"]["sources"][2].update(targetRevision="branch"),
            lambda app: app["spec"]["sources"][0]["helm"].update(valueFiles=["other.yaml"]),
            lambda app: app["spec"]["destination"].update(namespace="other"),
            lambda app: app["status"]["sync"].update(revisions=[RECOVER.CHART, "b" * 40, SHA]),
            lambda app: app["status"]["health"].update(status="Progressing"),
            lambda app: app["status"]["operationState"].update(phase="Running"),
            lambda app: app["status"]["operationState"].update(phase="Succeeded"),
            lambda app: app["status"]["operationState"].update(message="hook failed"),
            lambda app: app["status"]["operationState"].pop("finishedAt"),
        ]
        for change in changes:
            with self.subTest(change=change):
                self.cluster.app = copy.deepcopy(original)
                change(self.cluster.app)
                with self.assertRaises(RECOVER.Failure):
                    RECOVER.recover(SHA, True)
        self.assertFalse(any(args[0] == "argocd" for args, _ in self.commands.calls))

    def test_deployment_readiness_and_actual_core_digest_are_required(self):
        for name in self.cluster.resources:
            with self.subTest(name=name):
                deployment = self.cluster.resources[name]["deployment"]
                deployment["status"]["readyReplicas"] = 0
                with self.assertRaisesRegex(RECOVER.Failure, "deployment_not_ready"):
                    RECOVER.recover(SHA, True)
                deployment["status"]["readyReplicas"] = 1
        core_pod = self.cluster.resources["harbor-core"]["pods"]
        core_pod["status"]["containerStatuses"][0]["imageID"] = "registry/core@sha256:" + "f" * 64
        with self.assertRaisesRegex(RECOVER.Failure, "core_digest_mismatch"):
            RECOVER.recover(SHA, True)
        self.assertFalse(any(args[0] == "argocd" for args, _ in self.commands.calls))

    def test_changed_preflight_stops_mutation(self):
        before = RECOVER.preflight(SHA)
        with patch.object(RECOVER, "preflight", side_effect=[before, {**before, "uid": "changed"}]):
            with self.assertRaisesRegex(RECOVER.Failure, "preflight_changed"):
                RECOVER.recover(SHA, True)
        self.assertFalse(any(args[:3] == ("argocd", "app", "sync") for args, _ in self.commands.calls))

    def test_success_requires_new_exact_operation_and_both_postsync_hooks(self):
        before = RECOVER.preflight(SHA)
        self.cluster.succeed()
        original = copy.deepcopy(self.cluster.app)
        changes = [
            lambda app: app["status"]["operationState"].update(startedAt=before["operation_started"]),
            lambda app: app["status"]["operationState"]["syncResult"].update(
                revisions=[RECOVER.CHART, "b" * 40, SHA]),
            lambda app: app["status"]["operationState"]["syncResult"]["resources"].pop(),
            lambda app: app["status"]["operationState"]["syncResult"]["resources"][0].update(hookPhase="Failed"),
            lambda app: app["metadata"].update(uid="00000000-0000-4000-8000-000000000099"),
        ]
        for change in changes:
            with self.subTest(change=change):
                self.cluster.app = copy.deepcopy(original)
                change(self.cluster.app)
                with self.assertRaises(RECOVER.Failure):
                    RECOVER.postflight(SHA, before)

    def test_cli_withholds_subprocess_credentials_and_requires_isolation(self):
        output = io.StringIO()
        with patch.object(RECOVER, "recover", side_effect=subprocess.CalledProcessError(
                1, ["secret"], stderr="private-credential")), contextlib.redirect_stdout(output):
            self.assertEqual(RECOVER.main(["--expected-sha", SHA, "--execute"]), 1)
        self.assertNotIn("private-credential", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["blocker"], "command_unavailable_or_failed")
        self.patches[3].stop()
        result = subprocess.run(["python3", str(ROOT / "scripts/harbor-full-sync.py"), "--help"],
                                capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("python3 -I", result.stderr)

    def test_sigterm_cleans_server_and_restores_signal_handler(self):
        previous = signal.getsignal(signal.SIGTERM)
        self.commands.interrupt_sync = True
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(RECOVER.main(["--expected-sha", SHA, "--execute"]), 1)
        self.assertEqual(json.loads(output.getvalue())["blocker"], "interrupted")
        self.killpg.assert_called_once_with(12345, signal.SIGTERM)
        self.assertFalse(Path(self.config).parent.exists())
        self.assertEqual(self.commands.current_context, "operator")
        self.assertIs(signal.getsignal(signal.SIGTERM), previous)


if __name__ == "__main__":
    unittest.main()
