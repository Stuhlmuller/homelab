#!/usr/bin/env python3
"""Exercise fixed-scope Harbor recovery without cluster or Git mutations."""
import contextlib
import copy
import importlib.util
import io
import json
import signal
from pathlib import Path
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
CONTEXT = "harbor-full-sync-" + "f" * 32


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
        if args == ("kubectl", "config", "get-contexts", "-o", "name"):
            return "\n".join(self.contexts) + "\n"
        if args[:3] == ("kubectl", "config", "set-context"):
            assert args == ("kubectl", "config", "set-context", CONTEXT, "--cluster", "homelab",
                            "--user", "admin", "--namespace", "argocd")
            self.contexts[CONTEXT] = {"cluster": "homelab", "user": "admin", "namespace": "argocd"}
            return ""
        if args == ("kubectl", "config", "delete-context", CONTEXT):
            del self.contexts[CONTEXT]
            return ""
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
        self.patches = [patch.object(RECOVER, "run", self.commands),
                        patch.object(RECOVER, "read", self.cluster.read),
                        patch.object(RECOVER, "uuid4", return_value=SimpleNamespace(hex="f" * 32))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_preview_has_no_argocd_mutation(self):
        self.assertEqual(RECOVER.recover(SHA), {"ready": True, "executed": False, "expected_sha": SHA})
        self.assertFalse(any(args[0] == "argocd" for args, _ in self.commands.calls))

    def test_execute_pins_every_source_and_verifies_hooks(self):
        result = RECOVER.recover(SHA, True)
        self.assertTrue(result["controller_verified"])
        self.assertTrue(result["postsync_hooks_verified"])
        actual = [(args, timeout) for args, timeout in self.commands.calls if args[0] == "argocd"]
        self.assertEqual(actual, [
            (("argocd", "app", "sync", "harbor", "--core", "--kube-context", CONTEXT,
              "--revisions", RECOVER.CHART,
              "--source-positions", "1", "--revisions", SHA, "--source-positions", "2",
              "--revisions", SHA, "--source-positions", "3", "--timeout", "900"), 930),
            (("argocd", "app", "wait", "harbor", "--core", "--kube-context", CONTEXT,
              "--sync", "--health", "--operation",
              "--timeout", "900"), 930),
        ])
        self.assertEqual(sum(args == ("git", "rev-parse", "HEAD") for args, _ in self.commands.calls), 3)
        self.assertEqual(self.commands.current_context, "operator")
        self.assertEqual(self.commands.contexts,
                         {"operator": {"cluster": "homelab", "user": "admin", "namespace": "default"}})

    def test_temporary_context_cleanup_on_sync_failure_and_when_already_absent(self):
        self.commands.fail_sync = True
        with self.assertRaises(subprocess.CalledProcessError):
            RECOVER.recover(SHA, True)
        self.assertNotIn(CONTEXT, self.commands.contexts)
        self.assertEqual(self.commands.current_context, "operator")
        self.commands.calls.clear()
        with RECOVER.argocd_context(RECOVER.kube_context()):
            del self.commands.contexts[CONTEXT]
        self.assertFalse(any(args[:3] == ("kubectl", "config", "delete-context")
                             for args, _ in self.commands.calls))

    def test_temporary_context_does_not_replace_existing_context_or_accept_changed_identity(self):
        self.commands.contexts[CONTEXT] = {"cluster": "other", "user": "other"}
        with self.assertRaisesRegex(RECOVER.Failure, "temporary_context_exists"):
            RECOVER.recover(SHA, True)
        self.assertEqual(self.commands.contexts[CONTEXT], {"cluster": "other", "user": "other"})
        with self.assertRaisesRegex(RECOVER.Failure, "kube_context_changed"):
            with RECOVER.argocd_context({"name": "operator", "cluster": "other", "user": "admin"}):
                self.fail("changed context was accepted")

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
        self.assertFalse(any(args[0] == "argocd" for args, _ in self.commands.calls))

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
        result = subprocess.run(["python3", str(ROOT / "scripts/harbor-full-sync.py"), "--help"],
                                capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("python3 -I", result.stderr)

    def test_sigterm_cleans_temporary_context_and_restores_signal_handler(self):
        previous = signal.getsignal(signal.SIGTERM)
        self.commands.interrupt_sync = True
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(RECOVER.main(["--expected-sha", SHA, "--execute"]), 1)
        self.assertEqual(json.loads(output.getvalue())["blocker"], "interrupted")
        self.assertNotIn(CONTEXT, self.commands.contexts)
        self.assertEqual(self.commands.current_context, "operator")
        self.assertIs(signal.getsignal(signal.SIGTERM), previous)


if __name__ == "__main__":
    unittest.main()
