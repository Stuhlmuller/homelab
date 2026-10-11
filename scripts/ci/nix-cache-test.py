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
from unittest.mock import patch
from datetime import datetime, timezone

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
                                     '(sleep 3; touch "$1") & wait', "fixture", str(marker)])
            self.assertEqual(result.returncode, 124)
            time.sleep(3)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(shutil.which("timeout"), "GNU timeout is supplied by the Nix shell")
    def test_cancellation_cleans_before_during_and_after_build(self):
        policy = {"url": "fixture", "publicKey": "fixture"}
        for stage in ("import", "build", "export"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                command = builder.attempt_command(policy)
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
                    self.assertFalse((root / "offline-check.lock").exists())
                    self.assertFalse(list(root.glob("check.*")))
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()

    def test_cancellation_only_signals_entire_owned_attempt(self):
        command = builder.attempt_command({"url": "fixture", "publicKey": "fixture"})
        for comm, args, expected in (("timeout", command, True), ("timeout", ["unrelated"], False), ("sh", command, False)):
            with self.subTest(comm=comm, args=args), tempfile.TemporaryDirectory() as temporary:
                proc = Path(temporary) / "1234"
                proc.mkdir()
                (proc / "comm").write_text(comm + "\n")
                (proc / "cmdline").write_bytes(b"\0".join(arg.encode() for arg in args) + b"\0")
                script = builder.CANCEL_SCRIPT.replace("/proc/", temporary + "/").replace("EXPECTED", shlex.quote(" ".join(command) + " "))
                result = subprocess.run(["sh", "-c", f'kill() {{ echo "SIGNAL:$*"; rm "{proc}/comm"; }};\n' + script], capture_output=True, text=True, check=True)
                self.assertEqual("SIGNAL:-TERM 1234" in result.stdout, expected)
        self.assertIn("remaining=20", builder.CANCEL_SCRIPT)

    def test_disconnect_cancels_original_pod(self):
        policy = {"url": "https://example.test", "publicKey": "fixture:key"}
        with patch.object(builder.subprocess, "run"), patch.object(builder.subprocess, "check_output", side_effect=[
                "tree", b"source", "/nix/store/a", "/nix/store/b", KeyboardInterrupt]), \
                patch.object(builder, "preflight", return_value=("nix-builder-original", "original-uid")), \
                patch.object(builder, "cancel") as cancel:
            with self.assertRaises(KeyboardInterrupt):
                builder.export(Path("unused"), policy)
            cancel.assert_called_once_with(policy, "nix-builder-original", "original-uid")

    def test_cancellation_refuses_replacement_pod(self):
        with patch.object(builder.subprocess, "check_output", return_value='{"metadata":{"uid":"replacement"}}'), \
                patch.object(builder.subprocess, "run") as signal:
            with self.assertRaises(ValueError):
                builder.cancel({"url": "fixture", "publicKey": "fixture"}, "nix-builder-original", "original")
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
