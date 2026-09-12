#!/usr/bin/env python3
"""Failure-path fixtures for n8n maintenance; no cluster or credential access."""
import copy
import hashlib
import importlib.util
import io
import json
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("checkpoint", ROOT / "scripts/n8n-paired-checkpoint.py")
checkpoint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checkpoint)
phase = checkpoint.phase
SESSION = "a" * 32
REVISION = "b" * 40


def base(app):
    return {"metadata": {"name": app, "annotations": {phase.PHASE: "normal", phase.SESSION: ""}},
            "spec": {"sources": ([{"repoURL": "https://charts.example", "chart": "app-template",
                                  "targetRevision": "4.4.0", "path": ".",
                                  "helm": {"valueFiles": ["original"]}},
                                 {"repoURL": phase.REPO, "targetRevision": "main", "ref": "values", "path": "."},
                                 {"repoURL": phase.REPO, "targetRevision": "main", "path": "clusters/homelab/apps/n8n"}]
                                if app == "n8n" else [{"repoURL": phase.REPO, "targetRevision": "main",
                                                       "path": "clusters/homelab/apps/n8n-postgres"}])}}


def live():
    result = {app: base(app) for app in phase.APPS}
    for item in result.values():
        item["status"] = {"health": {"status": "Healthy"}, "sync": {"status": "Synced", "revisions": [
            REVISION if source["repoURL"] == phase.REPO else source["targetRevision"] for source in item["spec"]["sources"]]}}
    return result


class CheckpointTests(unittest.TestCase):
    def test_capture_rechecks_prepared_revision_health_and_sync_before_outage(self):
        for state in ("OutOfSync", "Degraded", "changed-revision"):
            current = live()
            if state == "OutOfSync":
                current["n8n"]["status"]["sync"]["status"] = state
            elif state == "Degraded":
                current["n8n"]["status"]["health"]["status"] = state
            else:
                current["n8n"]["status"]["sync"]["revisions"][-1] = "c" * 40
            with patch.object(phase, "load_live", return_value=current), \
                    patch.object(checkpoint, "apply_phase") as apply, \
                    patch.object(checkpoint, "PodExitWatch") as watch, \
                    patch.object(checkpoint, "resume") as resume:
                with self.assertRaisesRegex(ValueError, "Healthy and Synced on prepared main"):
                    checkpoint.capture(Path("/unused"), {"revision": REVISION})
                apply.assert_not_called()
                watch.assert_not_called()
                resume.assert_not_called()

    def test_rendered_reader_configmap_references_match_namespace_and_hash(self):
        rendered = subprocess.run(["kubectl", "kustomize", str(ROOT / "clusters/homelab/apps/n8n-postgres-capture")],
                                  check=True, capture_output=True, text=True).stdout
        documents = rendered.split("\n---\n")
        configmaps = [doc for doc in documents if "\nkind: ConfigMap\n" in doc and
                      re.search(r"^  name: n8n-checkpoint-reader-", doc, re.MULTILINE)]
        self.assertEqual(len(configmaps), 1)
        expected = re.search(r"^  name: (n8n-checkpoint-reader-\S+)", configmaps[0], re.MULTILINE)[1]
        self.assertRegex(configmaps[0], r"(?m)^  namespace: automation$")
        pods = [doc for doc in documents if "\nkind: Pod\n" in doc]
        self.assertEqual(len(pods), 2)
        for pod in pods:
            self.assertRegex(pod, r"(?m)^  namespace: automation$")
            self.assertEqual(re.findall(r"^      name: (n8n-checkpoint-reader\S*)", pod, re.MULTILINE), [expected])

    def test_private_destination_rejects_temporary_storage_and_any_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with self.assertRaisesRegex(ValueError, "durable storage"):
                checkpoint.private_destination(path)
            (path / ".git").mkdir()
            with self.assertRaisesRegex(ValueError, "outside Git checkouts"):
                checkpoint.private_destination(path)

    def test_profile_preserves_baseline_and_restore(self):
        original = base("n8n")
        transformed = phase.profile(original, "stopped", SESSION)
        self.assertEqual(original, base("n8n"))
        self.assertEqual(transformed["spec"]["sources"][0]["helm"]["valuesObject"]["controllers"]["n8n"]["replicas"], 0)
        self.assertEqual(phase.profile(original, "normal", SESSION), original)

    def test_recovery_profiles_pin_all_git_sources_and_keep_markers(self):
        for app, target in (("n8n", "recovered"), ("n8n-postgres", "recovery-cold"), ("n8n-postgres", "recovered")):
            desired = phase.profile(base(app), target, SESSION, REVISION)
            self.assertEqual(phase.markers(desired), {phase.PHASE: target, phase.SESSION: SESSION})
            for source in desired["spec"]["sources"]:
                self.assertEqual(source["targetRevision"], REVISION if source["repoURL"] == phase.REPO else "4.4.0")
            if app == "n8n" or target == "recovered":
                self.assertEqual(desired["spec"]["sources"][-1]["path"], "clusters/homelab/apps/" + app)
        with self.assertRaises(ValueError):
            phase.profile(base("n8n"), "recovered", SESSION, "main")

    def test_recovery_guard_rejects_a_different_checkout_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            desired = phase.profile(base("n8n"), "recovered", SESSION, REVISION)
            path.write_text(json.dumps({"manifest": desired}))
            Path(str(path) + ".profile.json").write_text(json.dumps({"phase": "recovered", "session": SESSION, "revision": REVISION}))
            current = {app: phase.profile(base(app), "stopped" if app == "n8n" else "recovered", SESSION, REVISION) for app in phase.APPS}
            with self.assertRaisesRegex(ValueError, "bound to the prepared"):
                phase.check_guard(base("n8n"), "plan", ["plan", "-var-file=" + str(path)], current, "c" * 40)
            phase.check_guard(base("n8n"), "plan", ["plan", "-var-file=" + str(path)], current, REVISION)

    def test_synced_accepts_only_documented_default_source_path_normalization(self):
        desired = phase.profile(base("n8n"), "stopped", SESSION)
        actual = copy.deepcopy(desired)
        actual["spec"]["sources"][0].pop("path")
        actual["spec"]["sources"][1]["path"] = ""
        actual["status"] = {"sync": {"status": "Synced", "revisions": ["4.4.0", REVISION, REVISION]}}
        with patch.object(checkpoint, "kube", return_value=actual):
            self.assertTrue(checkpoint.application_synced("n8n", desired, REVISION))
            actual["spec"]["sources"][0]["path"] = "unexpected-chart-path"
            self.assertFalse(checkpoint.application_synced("n8n", desired, REVISION))
            actual["spec"]["sources"][0].pop("path")
            actual["spec"]["sources"][2]["targetRevision"] = "different"
            self.assertFalse(checkpoint.application_synced("n8n", desired, REVISION))
            actual["spec"]["sources"][2]["targetRevision"] = "main"
            actual["spec"]["sources"][0]["helm"]["valuesObject"]["controllers"]["n8n"]["replicas"] = 1
            self.assertFalse(checkpoint.application_synced("n8n", desired, REVISION))
        self.assertEqual(desired["spec"]["sources"][0]["path"], ".")

    def test_unpin_fetch_failure_leaves_recovered_service_untouched(self):
        current = {app: phase.profile(base(app), "recovered", SESSION, REVISION) for app in phase.APPS}
        with patch.object(phase, "load_live", return_value=current), \
                patch.object(checkpoint, "ready", return_value=True), \
                patch.object(checkpoint, "run", side_effect=subprocess.CalledProcessError(1, ["git", "fetch"])), \
                patch.object(checkpoint, "apply_phase") as apply:
            with self.assertRaises(subprocess.CalledProcessError):
                checkpoint.unpin(Path("/unused"), {"id": SESSION, "revision": REVISION})
            apply.assert_not_called()
        self.assertTrue(all(phase.markers(item)[phase.PHASE] == "recovered" for item in current.values()))

    def test_resume_rejects_unknown_or_impossible_phase_pairs_before_success(self):
        for app_phase, pg_phase in (("unexpected", "normal"), ("normal", "capture"), ("recovered", "cold")):
            current = live()
            for app, target in zip(phase.APPS, (app_phase, pg_phase)):
                current[app]["metadata"]["annotations"].update({phase.PHASE: target, phase.SESSION: SESSION})
            with patch.object(phase, "load_live", return_value=current), \
                    patch.object(checkpoint, "ready") as ready, \
                    patch.object(checkpoint, "write_json") as receipt, \
                    patch.object(checkpoint, "apply_phase") as apply:
                with self.assertRaisesRegex(ValueError, "unsupported checkpoint phase pair"):
                    checkpoint.resume(Path("/unused"), {"id": SESSION})
                ready.assert_not_called()
                receipt.assert_not_called()
                apply.assert_not_called()

    def test_resume_retry_waits_for_readers_before_fencing_and_restart(self):
        current = {app: phase.profile(base(app), "stopped" if app == "n8n" else "recovery-cold", SESSION, REVISION)
                   for app in phase.APPS}
        events = []

        def apply(_directory, _session, app, target):
            events.append((app, target))
            phase.validate_transition(app, phase.profile(base(app), target, SESSION, REVISION), current, SESSION)
            current[app] = phase.profile(base(app), target, SESSION, REVISION)

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(phase, "load_live", return_value=current), \
                patch.object(checkpoint, "wait_for", side_effect=lambda _predicate, _seconds, label: events.append(label)), \
                patch.object(checkpoint, "fence", side_effect=lambda *_args, **_kwargs: events.append("fence")), \
                patch.object(checkpoint, "talos_fence"), \
                patch.object(checkpoint, "apply_phase", side_effect=apply), \
                patch.object(checkpoint, "run", side_effect=AssertionError("resume must not fetch GitHub")):
            checkpoint.resume(Path(directory), {"id": SESSION, "revision": REVISION,
                              "writers": {app: {"name": app + "-old"} for app in phase.APPS}})
        self.assertEqual(events[:4], ["reader removal", "old writer removal", "fence", ("n8n-postgres", "recovered")])
        self.assertLess(events.index(("n8n-postgres", "recovered")), events.index(("n8n", "recovered")))

    def test_unpin_changed_sources_do_not_reconcile_main(self):
        current = {app: phase.profile(base(app), "recovered", SESSION, REVISION) for app in phase.APPS}
        with patch.object(phase, "load_live", return_value=current), \
                patch.object(checkpoint, "ready", return_value=True), \
                patch.object(checkpoint, "run", side_effect=["", subprocess.CalledProcessError(1, ["git", "diff"])]), \
                patch.object(checkpoint, "apply_phase") as apply:
            with self.assertRaises(subprocess.CalledProcessError):
                checkpoint.unpin(Path("/unused"), {"id": SESSION, "revision": REVISION})
            apply.assert_not_called()

    def test_unpin_retry_finishes_only_remaining_application(self):
        current = live()
        current["n8n"] = phase.profile(base("n8n"), "recovered", SESSION, REVISION)
        calls = []

        def apply(_directory, _session, app, target, **kwargs):
            calls.append((app, target, kwargs["expected_main_revision"]))
            phase.validate_transition(app, base(app), current, SESSION)
            current[app] = base(app)

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(phase, "load_live", return_value=current), \
                patch.object(checkpoint, "ready", return_value=True), \
                patch.object(checkpoint, "run", side_effect=["", "", "c" * 40]), \
                patch.object(checkpoint, "apply_phase", side_effect=apply):
            checkpoint.unpin(Path(directory), {"id": SESSION, "revision": REVISION})
        self.assertEqual(calls, [("n8n", "normal", "c" * 40)])

    def test_completed_unpin_is_idempotent_without_network(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(phase, "load_live", return_value=live()), \
                patch.object(checkpoint, "run", side_effect=AssertionError("completed unpin needs no GitHub")), \
                patch.object(checkpoint, "apply_phase") as apply:
            checkpoint.unpin(Path(directory), {"id": SESSION, "revision": REVISION})
            apply.assert_not_called()
            self.assertTrue(json.loads(next(Path(directory).glob("unpinned-*.json")).read_text())["already_normal"])

    def test_command_timeout_stops_child_and_grandchild_before_return(self):
        with tempfile.TemporaryDirectory() as directory:
            marker, ready = Path(directory) / "late-write", Path(directory) / "ready"
            grandchild = ("import signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                          f"pathlib.Path({str(ready)!r}).write_text('ready'); time.sleep(1); "
                          f"pathlib.Path({str(marker)!r}).write_text('late')")
            child = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{grandchild!r}]); time.sleep(10)"
            parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(10)"
            with self.assertRaises(subprocess.TimeoutExpired):
                checkpoint.run([sys.executable, "-c", parent], timeout=0.4)
            self.assertTrue(ready.exists(), "fixture must spawn the actual grandchild before timeout")
            time.sleep(1.1)
            self.assertFalse(marker.exists(), "a descendant wrote after command cancellation")

    def test_keyboard_interrupt_stops_owned_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            marker, ready = Path(directory) / "late-write", Path(directory) / "ready"
            child = ("import signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                     f"pathlib.Path({str(ready)!r}).write_text('ready'); time.sleep(1); "
                     f"pathlib.Path({str(marker)!r}).write_text('late')")
            parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(10)"
            real_popen = subprocess.Popen

            def start(command, **kwargs):
                process = real_popen(command, **kwargs)
                interrupted = False

                def communicate(**options):
                    nonlocal interrupted
                    if not interrupted:
                        interrupted = True
                        deadline = time.monotonic() + 3
                        while not ready.exists() and time.monotonic() < deadline:
                            time.sleep(0.01)
                        self.assertTrue(ready.exists())
                        raise KeyboardInterrupt
                    return process.communicate(**options)

                return SimpleNamespace(pid=process.pid, wait=process.wait, stdout=process.stdout,
                                       stderr=process.stderr, communicate=communicate)

            with patch.object(checkpoint.subprocess, "Popen", side_effect=start), self.assertRaises(KeyboardInterrupt):
                checkpoint.run([sys.executable, "-c", parent])
            time.sleep(1.1)
            self.assertFalse(marker.exists(), "a child wrote after interrupted command cleanup returned")

    def test_failed_command_reaping_prevents_automatic_resume(self):
        pods = [{"metadata": {"name": app + "-old", "uid": app, "resourceVersion": "1"},
                 "spec": {"nodeName": "worker", "volumes": [], "containers": [{"name": "app", "image": "pinned"}]},
                 "status": {"containerStatuses": [{"name": "app", "containerID": app}]}}
                for app in phase.APPS]
        session = {"id": SESSION, "revision": REVISION, "writers": {
            app: checkpoint.pod_identity(pod) for app, pod in zip(phase.APPS, pods)}}
        watch = MagicMock(observed=True, error=None)
        with patch.object(phase, "load_live", return_value=live()), \
                patch.object(checkpoint, "source_pods", return_value=pods), \
                patch.object(checkpoint, "fence"), \
                patch.object(checkpoint, "PodExitWatch", return_value=watch), \
                patch.object(checkpoint, "apply_phase", side_effect=checkpoint.CommandCleanupError("fixture")), \
                patch.object(checkpoint, "resume") as resume:
            with self.assertRaises(checkpoint.CommandCleanupError):
                checkpoint.capture(Path("/unused"), session)
            resume.assert_not_called()

    def test_unknown_profile_and_arbitrary_session_fail(self):
        for target, session in [("delete", SESSION), ("stopped", "../escape")]:
            with self.assertRaises(ValueError):
                phase.profile(base("n8n"), target, session)

    def test_postgres_cannot_stop_before_app(self):
        with self.assertRaises(ValueError):
            phase.validate_transition("n8n-postgres", phase.profile(base("n8n-postgres"), "cold", SESSION), live(), SESSION)

    def test_normal_cannot_jump_to_capture(self):
        current = live()
        current["n8n"] = phase.profile(base("n8n"), "stopped", SESSION)
        with self.assertRaises(ValueError):
            phase.validate_transition("n8n-postgres", phase.profile(base("n8n-postgres"), "capture", SESSION), current, SESSION)

    def test_application_cannot_resume_before_database(self):
        current = {app: phase.profile(base(app), "stopped" if app == "n8n" else "cold", SESSION) for app in phase.APPS}
        with self.assertRaises(ValueError):
            phase.validate_transition("n8n", base("n8n"), current, SESSION)

    def test_other_operator_session_rejected(self):
        current = live()
        current["n8n"] = phase.profile(base("n8n"), "stopped", "b" * 32)
        with self.assertRaises(ValueError):
            phase.validate_transition("n8n-postgres", phase.profile(base("n8n-postgres"), "cold", SESSION), current, SESSION)

    def test_default_terragrunt_blocked_during_active_session(self):
        current = live()
        current["n8n"] = phase.profile(base("n8n"), "stopped", SESSION)
        for command in ("plan", "apply", "destroy"):
            with self.assertRaises(ValueError):
                phase.check_guard(base("n8n-postgres"), command, [command], current)

    def test_no_maintenance_preserves_ordinary_plan(self):
        phase.check_guard(base("n8n"), "plan", ["plan", "-input=false"], live())

    def test_profile_cannot_change_image_or_other_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            data = {"manifest": phase.profile(base("n8n"), "stopped", SESSION)}
            data["manifest"]["spec"]["sources"][0]["helm"]["valueFiles"] = ["different"]
            path.write_text(json.dumps(data))
            Path(str(path) + ".profile.json").write_text(json.dumps({"phase": "stopped", "session": SESSION}))
            with self.assertRaises(ValueError):
                phase.check_guard(base("n8n"), "plan", ["plan", "-var-file=" + str(path)], live())

    def test_split_or_extra_variable_overrides_fail_before_default_return(self):
        for arguments in (["plan", "-var", "manifest={}"], ["plan", "-var=manifest={}"],
                          ["plan", "--var", "manifest={}"], ["plan", "--var=manifest={}"],
                          ["plan", "--var-file=/tmp/unreviewed.json"], ["plan", "--var-file", "/tmp/unreviewed.json"],
                          ["plan", "-var-file", "/tmp/unreviewed.json"],
                          ["plan", "-var-file=/tmp/closed.json", "-var-file", "/tmp/unreviewed.json"],
                          ["plan", "-var-file=/tmp/closed.json", "-var-file=/tmp/extra.json"]):
            with self.assertRaises(ValueError):
                phase.check_guard(base("n8n"), "plan", arguments, live())

    def test_capture_error_removes_readers_then_resumes_database_before_app(self):
        current = live()
        calls = []
        pods = []
        for app in phase.APPS:
            pods.append({"metadata": {"name": app + "-old", "uid": app, "resourceVersion": "1"},
                         "spec": {"nodeName": "worker", "volumes": [], "containers": [{"name": "app", "image": "pinned"}]},
                         "status": {"containerStatuses": [{"name": "app", "containerID": app}]}})
        session = {"id": SESSION, "revision": REVISION, "writers": {
            app: checkpoint.pod_identity(pod) for app, pod in zip(phase.APPS, pods)}}

        def apply(_directory, _session, app, target, **_kwargs):
            calls.append((app, target))
            current[app] = phase.profile(base(app), target, SESSION, REVISION)

        def watch(writer):
            result = MagicMock(writer=writer, observed=True, error=None)
            result.terminal = {"app": {"exitCode": 0}}
            return result

        observer = MagicMock(observations=1, error=None)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(phase, "load_live", return_value=current), \
                patch.object(checkpoint, "source_pods", return_value=pods), \
                patch.object(checkpoint, "fence"), patch.object(checkpoint, "talos_fence"), \
                patch.object(checkpoint, "apply_phase", side_effect=apply), \
                patch.object(checkpoint, "PodExitWatch", side_effect=watch), \
                patch.object(checkpoint, "CaptureFence", return_value=observer), \
                patch.object(checkpoint, "wait_for"), patch.object(checkpoint, "run", side_effect=AssertionError("resume must not fetch GitHub")), \
                patch.object(checkpoint, "stream_archive", side_effect=ValueError("reader failure")):
            with self.assertRaisesRegex(ValueError, "reader failure"):
                checkpoint.capture(Path(directory), session)
            self.assertFalse((Path(directory) / "paired-capture.json").exists())
        self.assertEqual(calls, [("n8n", "stopped"), ("n8n-postgres", "cold"),
                                ("n8n-postgres", "capture"), ("n8n-postgres", "recovery-cold"),
                                ("n8n-postgres", "recovered"), ("n8n", "recovered")])

    def test_modified_saved_plan_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "phase.plan"
            path.write_bytes(b"changed")
            Path(str(path) + ".n8n-permit.json").write_text(json.dumps({"plan_sha256": "0" * 64}))
            with self.assertRaises(ValueError):
                phase.check_guard(base("n8n"), "apply", ["apply", str(path)], live())

    def test_saved_plan_stale_phase_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "phase.plan"
            path.write_bytes(b"plan")
            Path(str(path) + ".n8n-permit.json").write_text(json.dumps({"plan_sha256": phase.digest(path), "before": {}}))
            with self.assertRaises(ValueError):
                phase.check_guard(base("n8n"), "apply", ["apply", str(path)], live())

    def test_plan_cannot_replace_or_change_extra_resources(self):
        desired = base("n8n")
        change = {"address": "kubernetes_manifest.this", "change": {"actions": ["update"], "after": {"manifest": desired}}}
        checkpoint.validate_plan({"resource_changes": [change]}, desired)
        for actions in (["create"], ["delete", "create"]):
            item = copy.deepcopy(change)
            item["change"]["actions"] = actions
            with self.assertRaises(ValueError):
                checkpoint.validate_plan({"resource_changes": [item]}, desired)
        with self.assertRaises(ValueError):
            checkpoint.validate_plan({"resource_changes": [change, change]}, desired)

    def test_node_reboot_or_unknown_state_rejected(self):
        expected = {"worker": {"boot_id": "a", "ready": True}}
        for current in ({"worker": {"boot_id": "b", "ready": True}}, {"worker": {"boot_id": "a", "ready": False}}):
            with self.assertRaises(ValueError):
                checkpoint.check_nodes(expected, current)

    def test_live_node_container_rejected(self):
        nodes = {"worker": {"address": "10.0.0.1"}}
        output = "NODE NAMESPACE ID IMAGE PID STATUS\n10.0.0.1 k8s.io automation/n8n-old:app:123 sha256:abc 42 CONTAINER_RUNNING\n"
        with self.assertRaises(ValueError):
            checkpoint.check_talos_rows(output, nodes, [{"name": "n8n-old"}])
        checkpoint.check_talos_rows(output.replace("42 CONTAINER_RUNNING", "0 CONTAINER_EXITED"), nodes, [{"name": "n8n-old"}])

    def test_missing_node_response_rejected(self):
        with self.assertRaises(ValueError):
            checkpoint.check_talos_rows("NODE NAMESPACE ID IMAGE PID STATUS\n", {"worker": {"address": "10.0.0.1"}}, [])

    def test_unchanged_initial_pod_starts_watch_before_any_stop(self):
        real_popen, arguments = subprocess.Popen, []
        writer = {"name": "n8n-original", "uid": "original", "containers": {"app": "container"}}
        event = {"type": "ADDED", "object": {"metadata": {"uid": "original"}, "status": {
            "containerStatuses": [{"name": "app", "containerID": "container", "state": {"running": {}}}]}}}

        def start(command, **kwargs):
            arguments.extend(command)
            return real_popen([sys.executable, "-u", "-c",
                               "import sys,time; print(sys.argv[1],flush=True); time.sleep(10)",
                               json.dumps(event)], **kwargs)

        with patch.object(checkpoint.subprocess, "Popen", side_effect=start):
            watch = checkpoint.PodExitWatch(writer)
            try:
                deadline = time.monotonic() + 3
                while not watch.observed and watch.error is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(watch.observed)
                self.assertIsNone(watch.error)
                self.assertEqual(watch.terminal, {})
                self.assertIn("--watch", arguments)
                self.assertNotIn("--watch-only", arguments)
            finally:
                watch.close()

    def test_shutdown_requires_observed_clean_exit(self):
        watch = object.__new__(checkpoint.PodExitWatch)
        watch.writer, watch.error, watch.terminal = {"containers": {"app": "id"}}, None, {}
        with self.assertRaises(ValueError):
            watch.require_clean()
        for code in (1, 137):
            watch.terminal = {"app": {"exitCode": code}}
            with self.assertRaises(ValueError):
                watch.require_clean()
        watch.terminal = {"app": {"exitCode": 0, "signal": 0}}
        watch.require_clean()

    def test_archive_complete_read_without_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.tar"
            with tarfile.open(path, "w") as archive:
                item = tarfile.TarInfo("./config")
                item.size = 7
                archive.addfile(item, io.BytesIO(b"private"))
            result = checkpoint.verify_archive(path, "n8n")
            self.assertEqual(result["members"], 1)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_archive_escape_symlink_or_missing_state_rejected(self):
        for name, kind in [("../config", tarfile.REGTYPE), ("config", tarfile.SYMTYPE), ("unrelated", tarfile.REGTYPE)]:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "app.tar"
                with tarfile.open(path, "w") as archive:
                    item = tarfile.TarInfo(name)
                    item.type = kind
                    archive.addfile(item)
                with self.assertRaises(ValueError):
                    checkpoint.verify_archive(path, "n8n")

    def test_real_reader_stream_matches_remote_digest_and_rejects_links(self):
        # The normal Nix gate supplies GNU find/tar/coreutils; macOS's BSD find
        # cannot execute the Debian reader syntax outside that environment.
        found = subprocess.run(["find", "--version"], capture_output=True, text=True, check=False)
        if found.returncode or not shutil.which("sha256sum"):
            self.skipTest("run the repository Nix gate for the actual GNU reader fixture")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            (source / "config").write_bytes(b"synthetic fixture")
            (source / "binary").write_bytes(bytes(range(256)) * 64)
            script = (ROOT / "clusters/homelab/apps/n8n-postgres-capture/read.sh").read_text()
            script = script.replace("/source", shlex.quote(str(source)))
            prelude = "id() { printf '1000\\n'; }; findmnt() { printf 'one-source-mount\\n'; };\n"
            result = subprocess.run(["bash", "-c", prelude + script, "fixture", "n8n"], capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertIn("archive-sha256: " + hashlib.sha256(result.stdout).hexdigest() + "  -", result.stderr.decode())
            archive = Path(directory) / "n8n.tar"
            archive.write_bytes(result.stdout)
            self.assertEqual(checkpoint.verify_archive(archive, "n8n")["members"], 2)
            (source / "escape").symlink_to("/not-a-source")
            result = subprocess.run(["bash", "-c", prelude + script, "fixture", "n8n"], capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")

    def test_receipt_is_exclusive_and_fsyncs_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            with patch.object(checkpoint, "fsync_directory") as sync:
                checkpoint.write_json(path, {"complete": True})
                sync.assert_called_once_with(path.parent)
            with self.assertRaises(FileExistsError):
                checkpoint.write_json(path, {"complete": False})


if __name__ == "__main__":
    unittest.main()
