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
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("checkpoint", ROOT / "scripts/n8n-paired-checkpoint.py")
checkpoint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checkpoint)
phase = checkpoint.phase
SESSION = "a" * 32


def base(app):
    return {"metadata": {"name": app, "annotations": {phase.PHASE: "normal", phase.SESSION: ""}},
            "spec": {"sources": ([{"helm": {"valueFiles": ["original"]}}, {"ref": "values"},
                                  {"path": "clusters/homelab/apps/n8n"}] if app == "n8n" else
                                 [{"path": "clusters/homelab/apps/n8n-postgres"}])}}


def live():
    return {app: base(app) for app in phase.APPS}


class CheckpointTests(unittest.TestCase):
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
        session = {"id": SESSION, "revision": "revision", "writers": {
            app: checkpoint.pod_identity(pod) for app, pod in zip(phase.APPS, pods)}}

        def apply(_directory, _session, app, target, **_kwargs):
            calls.append((app, target))
            current[app] = phase.profile(base(app), target, SESSION)

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
                patch.object(checkpoint, "wait_for"), patch.object(checkpoint, "run", return_value=""), \
                patch.object(checkpoint, "stream_archive", side_effect=ValueError("reader failure")):
            with self.assertRaisesRegex(ValueError, "reader failure"):
                checkpoint.capture(Path(directory), session)
            self.assertFalse((Path(directory) / "paired-capture.json").exists())
        self.assertEqual(calls, [("n8n", "stopped"), ("n8n-postgres", "cold"),
                                ("n8n-postgres", "capture"), ("n8n-postgres", "cold"),
                                ("n8n-postgres", "normal"), ("n8n", "normal")])

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
