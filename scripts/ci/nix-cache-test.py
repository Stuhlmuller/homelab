#!/usr/bin/env python3
"""Release layout preserves signatures and rejects unsigned or unsafe entries."""

import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import subprocess
import shutil
import time
import signal
import shlex
import unittest
from unittest.mock import ANY, patch
from datetime import datetime, timezone

ATTEMPT_ID = "d68b1eb0-2a1b-45a8-9b88-a662be678ebb"
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("cache", ROOT / "scripts/nix-cache.py")
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)
spec = importlib.util.spec_from_file_location("builder", ROOT / "scripts/nix-builder.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class CacheLayoutTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("timeout"), "GNU timeout is supplied by the Nix shell")
    def test_remote_deadline_stops_children(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "surviving-child"
            result = subprocess.run(["timeout", "--kill-after=1s", "1s", "sh", "-c",
                                     'trap "" TERM; (sleep 3; touch "$1") & wait', "fixture", str(marker)])
            self.assertEqual(result.returncode, -signal.SIGKILL)
            time.sleep(3)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(shutil.which("timeout"), "GNU timeout is supplied by the Nix shell")
    def test_deadline_retains_lock_before_during_and_after_build(self):
        policy = {"url": "fixture", "publicKey": "fixture"}
        for stage in ("import", "build", "export"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                command = builder.attempt_command(policy, ATTEMPT_ID)
                command[1] = "--kill-after=1s"
                script = command[5]
                beginning = script.index('test "$(cat /sys/fs/cgroup/memory.max)"')
                ending = script.index('job="$(mktemp')
                script = script[:beginning] + "mkdir /workspace/offline-check.lock\n" + script[ending:]
                blocked = 'touch /workspace/started; sleep 30'
                script = script.replace('tar -x -C "$job/source"', blocked if stage == "import" else "true")
                script = script.replace(shlex.join(builder.build_command(policy)), blocked if stage == "build" else "true")
                script = script.replace('nix copy --to "file://$job/cache" $(cat "$job/outputs")', blocked if stage == "export" else "true")
                script = script.replace('tar -c -C "$job/cache" .', "true").replace("/workspace", str(root))
                command[5] = script
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    deadline = time.monotonic() + 5
                    while not (root / "started").exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue((root / "started").exists())
                    process.send_signal(signal.SIGTERM)
                    process.wait(timeout=5)
                    self.assertTrue((root / "offline-check.lock").exists())
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()

    def test_cancellation_only_signals_entire_owned_attempt(self):
        command = builder.attempt_command({"url": "fixture", "publicKey": "fixture"}, ATTEMPT_ID)
        for comm, args, expected in (("timeout", command, True), ("timeout", ["timeout", "old policy and source", command[-1]], True),
                                     ("timeout", ["timeout", "homelab-offline-attempt:wrong-id"], False), ("sh", command, False)):
            with self.subTest(comm=comm, args=args), tempfile.TemporaryDirectory() as temporary:
                proc = Path(temporary) / "1234"
                proc.mkdir()
                (proc / "comm").write_text(comm + "\n")
                (proc / "stat").write_text("1234 (timeout) S 1 1234 0\n")
                (proc / "cmdline").write_bytes(b"\0".join(arg.encode() for arg in args) + b"\0")
                script = builder.CANCEL_SCRIPT.replace("/proc/", temporary + "/").replace("EXPECTED", shlex.quote("homelab-offline-attempt:" + ATTEMPT_ID))
                result = subprocess.run(["sh", "-c", f'kill() {{ echo "SIGNAL:$*"; rm "{proc}/comm" "{proc}/stat"; }};\n' + script], capture_output=True, text=True, check=True)
                self.assertEqual("SIGNAL:-TERM -1234" in result.stdout, expected)
        self.assertIn('kill -KILL "-$pid"', builder.CANCEL_SCRIPT)

    def test_cancellation_kills_child_after_supervisor_exit_before_unlock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            supervisor, child = root / "1234", root / "5678"
            supervisor.mkdir()
            child.mkdir()
            (supervisor / "comm").write_text("timeout\n")
            (supervisor / "cmdline").write_bytes(b"homelab-offline-attempt:" + ATTEMPT_ID.encode() + b"\0")
            (supervisor / "stat").write_text("1234 (timeout) S 1 1234 0\n")
            (child / "stat").write_text("5678 (TERM ignoring child) S 1 1234 0\n")
            lock = root / "offline-check.lock"
            lock.mkdir()
            (lock / "owner").write_text("1234\n")
            script = builder.CANCEL_SCRIPT.replace("/proc/", temporary + "/").replace("/workspace", temporary)
            script = script.replace("EXPECTED", shlex.quote("homelab-offline-attempt:" + ATTEMPT_ID)).replace("remaining=10", "remaining=1").replace("sleep 1", "true")
            signal_fixture = f'kill() {{ echo "SIGNAL:$*"; if [ "$1" = -TERM ]; then rm "{supervisor}/comm" "{supervisor}/stat"; else test -d "{lock}"; rm "{child}/stat"; fi; }};\n'
            result = subprocess.run(["sh", "-c", signal_fixture + script], capture_output=True, text=True, check=True)
            self.assertIn("SIGNAL:-KILL -1234", result.stdout)
            self.assertFalse(lock.exists())

    def test_cleanup_keeps_supervision_when_command_exits_before_descendant(self):
        policy = {"url": "fixture", "publicKey": "fixture"}
        for state in ("S", "Z"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                proc = root / "5678"
                proc.mkdir()
                (proc / "stat").write_text(f"5678 (TERM ignoring child) {state} 1 1234 0\n")
                lock = root / "offline-check.lock"
                lock.mkdir()
                (lock / "owner").write_text("1234\n")
                script = builder.attempt_command(policy, ATTEMPT_ID)[5]
                script = script[:script.index('test "$(cat /sys/fs/cgroup/memory.max)"')]
                script = script.replace("pid=$PPID", "pid=1234").replace("/proc/", temporary + "/").replace("/workspace", temporary)
                script = script.replace("remaining=10", "remaining=1").replace("sleep 1", "true")
                script = f'kill() {{ echo "SIGNAL:$*"; test -d "{lock}"; }};\n' + script + "trap cleanup EXIT\nfalse\n"
                result = subprocess.run(["sh", "-ec", script], capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertEqual("SIGNAL:-KILL -1234" in result.stdout, state == "S")
                self.assertEqual(lock.exists(), state == "S")

    def test_idle_scan_allows_readiness_probe_and_rejects_supervised_attempt(self):
        command = builder.attempt_command({"url": "fixture", "publicKey": "fixture"}, ATTEMPT_ID)
        script = command[5]
        script = script[script.index("for proc in /proc/"):script.index('test "$(nix eval')]
        for comm, args, expected in (("nix", ["nix", "store", "info"], 0),
                                     ("timeout", ["timeout", "unrelated"], 0),
                                     ("timeout", command, 1)):
            with self.subTest(comm=comm, args=args), tempfile.TemporaryDirectory() as temporary:
                proc = Path(temporary) / "1234"
                proc.mkdir()
                (proc / "comm").write_text(comm + "\n")
                (proc / "cmdline").write_bytes(b"\0".join(arg.encode() for arg in args) + b"\0")
                result = subprocess.run(["sh", "-ec", script.replace("/proc/", temporary + "/")], capture_output=True, text=True)
                self.assertEqual(result.returncode, expected)

    def test_disconnect_cancels_original_pod(self):
        policy = {"url": "https://example.test", "publicKey": "fixture:key"}
        with patch.object(builder.subprocess, "run"), patch.object(builder.subprocess, "check_output", side_effect=[
                "tree", b"source", "/nix/store/a", "/nix/store/b", KeyboardInterrupt]), \
                patch.object(builder, "preflight", return_value=("nix-builder-original", "original-uid")), \
                patch.object(builder, "cancel") as cancel:
            with self.assertRaises(KeyboardInterrupt):
                builder.export(Path("unused"), policy)
            cancel.assert_called_once_with("nix-builder-original", "original-uid", ANY)

    def test_cancellation_refuses_replacement_pod(self):
        with patch.object(builder.subprocess, "check_output", return_value='{"metadata":{"uid":"replacement"}}'), \
                patch.object(builder.subprocess, "run") as signal:
            with self.assertRaises(ValueError):
                builder.cancel("nix-builder-original", "original", ATTEMPT_ID)
            signal.assert_not_called()

    def test_resource_preflight_rejects_pressure_stale_metrics_and_low_headroom(self):
        now = datetime(2026, 10, 11, tzinfo=timezone.utc)
        timestamp = "2026-10-11T00:00:00Z"
        conditions = [{"type": "Ready", "status": "True"}] + [
            {"type": name, "status": "False"} for name in ("MemoryPressure", "DiskPressure", "PIDPressure")]
        nodes = {"items": [{"metadata": {"name": "worker"}, "status": {
            "conditions": conditions, "allocatable": {"memory": "8Gi"}}}]}
        leases = {"items": [{"metadata": {"name": "worker"}, "spec": {"renewTime": timestamp}}]}
        metric = {"metadata": {"name": "worker"}, "timestamp": timestamp, "usage": {"memory": "6Gi"}}
        pod = {"metadata": {"name": "nix-builder-fixture"}, "spec": {"nodeName": "worker", "containers": [
            {"name": "nix", "resources": {"requests": {"memory": "1Gi"}, "limits": {"memory": "1Gi"}}}]},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]}}
        builder.verify_preflight(nodes, leases, {"items": [metric]}, pod, now)
        for field, bad in (("timestamp", "2026-10-10T23:55:00Z"), ("usage", {"memory": "7Gi"})):
            original = metric[field]
            metric[field] = bad
            with self.assertRaises(ValueError):
                builder.verify_preflight(nodes, leases, {"items": [metric]}, pod, now)
            metric[field] = original
        conditions[1]["status"] = "True"
        with self.assertRaises(ValueError):
            builder.verify_preflight(nodes, leases, {"items": [metric]}, pod, now)

    def test_builder_archive_rejects_escape_and_symlinks(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("/escape", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                archive = io.BytesIO()
                with tarfile.open(fileobj=archive, mode="w") as stream:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    stream.addfile(member)
                with self.assertRaises(ValueError):
                    builder.unpack(archive.getvalue(), Path(temporary))

    def test_shared_nar_preserves_signed_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "nar").mkdir()
            (root / "nar/shared.nar.xz").write_bytes(b"fixture")
            fields = "StorePath: /nix/store/fixture\nNarHash: sha256:fixture\nNarSize: 7\nReferences: \nSig: fixture:signature\n"
            for name in ("a", "b"):
                (root / f"{name}.narinfo").write_text("URL: nar/shared.nar.xz\n" + fields)
            cache.flatten(root)
            for name in ("a", "b"):
                self.assertEqual((root / f"{name}.narinfo").read_text(), "URL: shared.nar.xz\n" + fields)
            self.assertEqual((root / "shared.nar.xz").read_bytes(), b"fixture")

    def test_unsigned_and_traversal_are_rejected(self):
        for entry in ("URL: nar/file.nar.xz\n", "URL: ../private\nSig: fixture:signature\n"):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "a.narinfo").write_text(entry)
                with self.assertRaises(ValueError):
                    cache.flatten(root)


if __name__ == "__main__":
    unittest.main()
