#!/usr/bin/env python3
"""Offline failures/routing contracts; native image CI supplies execution proof."""
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("fixture_docker", ROOT / "scripts/ci/octelium-restore-docker.py")
DOCKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCKER)
IMAGE = "sha256:" + "a" * 64


class DockerContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        probe = self.root / "probe"
        probe.write_text("synthetic")
        self.backend = DOCKER.DockerFixtures(IMAGE, probe)

    def test_mutable_image_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            DOCKER.DockerFixtures("image:latest", self.root / "probe")

    def test_exec_uses_absolute_image_tools_after_launcher(self):
        commands = {name: f"/usr/lib/postgresql/14/bin/{name}" for name in DOCKER.PG_COMMANDS}
        commands.update({"mkdir": "/usr/bin/mkdir", "cat": "/usr/bin/cat", "tar": "/usr/bin/tar", "/bin/sh": "/bin/sh"})
        for name, path in commands.items():
            with self.subTest(name=name):
                self.assertEqual(self.backend.exec_command("synthetic-container", name, "fixture"),
                                 ["docker", "exec", "synthetic-container", self.backend.boundary.LAUNCHER, path, "fixture"])
        with patch.object(DOCKER.subprocess, "run") as run:
            self.backend.execute("synthetic-container", "pg_restore", "--list", "/backup/archive")
        command = run.call_args.args[0]
        self.assertEqual(command[:5], ["docker", "exec", "synthetic-container",
                                     self.backend.boundary.LAUNCHER, "/usr/lib/postgresql/14/bin/pg_restore"])
        self.assertNotIn("--privileged", command)

    def test_unknown_image_command_cannot_fall_back_to_path(self):
        with patch.object(DOCKER.subprocess, "run") as run:
            for command in ((), ("curl",), ("/tmp/psql",), ("sh",)):
                with self.subTest(command=command), self.assertRaises(ValueError):
                    self.backend.execute("synthetic-container", *command)
        run.assert_not_called()

    def test_unexpected_exec_failure_has_bounded_stderr_without_stdout(self):
        error = subprocess.CalledProcessError(1, ["synthetic"], output="synthetic stdout", stderr="x" * 512 + "tail")
        with patch.object(DOCKER.subprocess, "run", side_effect=error):
            with self.assertRaises(subprocess.CalledProcessError) as failure:
                self.backend.execute("synthetic-container", "mkdir", "/work/socket")
        note = failure.exception.__notes__[0]
        self.assertIn("x" * 512, note)
        self.assertNotIn("tail", note)
        self.assertNotIn("synthetic stdout", note)
        self.assertLess(len(note), 600)
        result = subprocess.CompletedProcess([], 1, "", "expected fixture failure")
        with patch.object(DOCKER.subprocess, "run", return_value=result) as run:
            self.assertIs(self.backend.execute("synthetic-container", "/bin/sh", "fixture", check=False), result)
        self.assertFalse(run.call_args.kwargs["check"])

    def test_inspection_routes_to_disposable_restored_database(self):
        self.backend.root = self.root
        self.backend.source = "source-container"
        self.backend.restore = "restore-container"
        self.backend.work = self.root / "case/work"
        with patch.object(self.backend, "execute") as execute:
            self.backend.run("psql", "-h", str(self.backend.work / "restore-drill/socket"), "-d", "octelium")
            self.assertEqual(execute.call_args.args[:4],
                             ("restore-container", "psql", "-h", "/work/restore-drill/socket"))
            self.backend.run("psql", "-h", str(self.root / "socket"), "-d", "octelium")
            self.assertEqual(execute.call_args.args[:4], ("source-container", "psql", "-h", "/work/socket"))
        with self.assertRaises(ValueError):
            self.backend.run("curl", "https://example.invalid")

    def test_restore_mounts_only_synthetic_readonly_inputs(self):
        backups, work = self.root / "backups", self.root / "work"
        backups.mkdir()
        work.mkdir()
        (backups / "synthetic.dump").write_text("synthetic")
        script = ROOT / "clusters/homelab/apps/octelium-storage/restore-drill-candidate/restore-drill.sh"
        result = subprocess.CompletedProcess([], 1, "", "expected synthetic failure")
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w"):
            pass
        with patch.object(self.backend, "docker", return_value=subprocess.CompletedProcess([], 0, '""', "")) as docker, \
                patch.object(self.backend, "read_binary", return_value=stream.getvalue()) as read, \
                patch.object(self.backend, "execute", side_effect=[result,
                    subprocess.CompletedProcess([], 0, DOCKER.CONSOLE_MARKER + "positive-done", ""),
                    result]) as execute:
            self.assertIs(self.backend.drill(backups, work, script), result)
        command = docker.call_args_list[0].args
        self.assertIn(f"type=bind,src={backups},dst=/backup,readonly", command)
        self.assertIn(f"type=bind,src={script},dst=/tests/restore-drill.sh,readonly", command)
        self.assertIn(IMAGE, command)
        self.assertNotIn("--entrypoint", command)
        self.assertEqual(execute.call_args.args[1:],
                         ("/bin/sh", "/tests/restore-drill.sh", "/backup", "/work"))
        self.assertFalse(execute.call_args.kwargs["check"])
        self.assertEqual(read.call_args.args[2:], ("tar", "-C", "/work", "-cf", "-", "."))
        self.assertEqual(len(docker.call_args_list), 3)
        self.assertIn("exec </dev/null >/dev/null 2>&1", command[-1])
        self.assertEqual(docker.call_args_list[-1].args, ("docker", "logs", self.backend.restore))

    def test_pid1_null_descriptors_are_verified_in_running_container(self):
        with patch.object(self.backend, "docker", return_value=subprocess.CompletedProcess([], 0, '\"\"', "")), \
                patch.object(self.backend, "execute") as execute:
            name = self.backend.start_container()
        self.assertEqual(execute.call_args.args, (name, "/bin/sh", "-ec",
                         'for fd in 0 1 2; do test "$(readlink /proc/1/fd/$fd)" = /dev/null; done'))

    def test_procfd_positive_control_must_observe_canary_before_drill(self):
        backups, work = self.root / "backups", self.root / "work"
        backups.mkdir()
        work.mkdir()
        result = subprocess.CompletedProcess([], 0, "positive-done", "")
        with patch.object(self.backend, "start_container", return_value="synthetic"), \
                patch.object(self.backend, "execute", return_value=result) as execute:
            with self.assertRaisesRegex(RuntimeError, "positive control"):
                self.backend.drill(backups, work, self.root / "script")
        self.assertEqual(execute.call_count, 1)
        self.assertIn("rm /work/console-probe-client.executed", execute.call_args.args[-1])

    def test_host_or_shared_pid_namespace_is_rejected(self):
        for mode in ('host', 'container:foreign'):
            with self.subTest(mode=mode), patch.object(self.backend, "docker", side_effect=[
                    subprocess.CompletedProcess([], 0, "started", ""),
                    subprocess.CompletedProcess([], 0, '"' + mode + '"', "")]):
                with self.assertRaisesRegex(RuntimeError, "private PID namespace"):
                    self.backend.start_container()

    def test_all_public_streams_reject_private_canary(self):
        for channel in range(4):
            streams = ["", "", "", ""]
            streams[channel] = DOCKER.CONSOLE_MARKER
            result = subprocess.CompletedProcess([], 0, *streams[:2])
            logs = subprocess.CompletedProcess([], 0, *streams[2:])
            with self.subTest(channel=channel), self.assertRaisesRegex(RuntimeError, "marker escaped"):
                DOCKER.check_console(result, logs)

    def test_success_requires_both_private_native_execution_receipts(self):
        DOCKER.check_probe_receipts(self.root, False)
        with self.assertRaisesRegex(RuntimeError, "did not execute"):
            DOCKER.check_probe_receipts(self.root, True)
        for mode in ("client", "server"):
            path = self.root / f"console-probe-{mode}.executed"
            path.write_text("15\n")
            path.chmod(0o600)
        DOCKER.check_probe_receipts(self.root, True)
        path.write_text("5\n")
        with self.assertRaisesRegex(RuntimeError, "Incomplete"):
            DOCKER.check_probe_receipts(self.root, False)
        path.write_text("15\n")
        path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "Invalid private"):
            DOCKER.check_probe_receipts(self.root, True)

    def test_probe_skips_postgres_ancestors_but_checks_shell_ancestors(self):
        # An inert procfs-shaped tree tests the real shell selection logic. Linux
        # CI still supplies actual procfd permissions and pipe behavior.
        proc, work = self.root / "proc", self.root / "work"
        work.mkdir()
        private = work / "restore-drill"
        private.mkdir()
        log = private / "details.log"
        for pid in (os.getpid(), 1):
            node = proc / str(pid)
            (node / "fd").mkdir(parents=True)
            (node / "comm").write_text("sh\n")
            (node / "status").write_text("PPid:\t1\n" if pid != 1 else "PPid:\t0\n")
            for fd in (1, 2, 3, 4):
                (node / "fd" / str(fd)).symlink_to("/dev/null")
        parent = proc / str(os.getpid())
        (parent / "fd/1").unlink()
        (parent / "fd/1").symlink_to(log)
        script = self.root / "probe.sh"
        script.write_text(DOCKER.CONSOLE_PROBE.read_text().replace("/proc/", str(proc) + "/")
                          .replace("/work/", str(work) + "/"))
        for process in ("postgres", "sh"):
            (parent / "comm").write_text(process + "\n")
            log.write_text("original\n")
            subprocess.run(["sh", str(script), "client"], check=True, capture_output=True, timeout=5)
            self.assertEqual(DOCKER.CONSOLE_MARKER in log.read_text(), process == "sh")
            receipt = work / "console-probe-client.executed"
            self.assertGreaterEqual(int(receipt.read_text()), 8)

    def test_archive_rejects_traversal_links_devices_and_oversized_files(self):
        for kind in ("traversal", "symlink", "hardlink", "device", "size"):
            with self.subTest(kind=kind):
                stream = io.BytesIO()
                member = tarfile.TarInfo("../outside" if kind == "traversal" else "fixture")
                if kind == "symlink":
                    member.type, member.linkname = tarfile.SYMTYPE, "../outside"
                elif kind == "hardlink":
                    member.type, member.linkname = tarfile.LNKTYPE, "../outside"
                elif kind == "device":
                    member.type = tarfile.CHRTYPE
                elif kind == "size":
                    member.size = DOCKER.MAX_FILES + 1
                if kind == "size":
                    stream.write(member.tobuf() + b"\0" * 1024)
                else:
                    with tarfile.open(fileobj=stream, mode="w") as archive:
                        archive.addfile(member)
                with self.assertRaises(ValueError):
                    DOCKER.extract_fixture(stream.getvalue(), self.root)
                self.assertFalse((self.root / "fixture").exists())

    def test_regular_fixture_output_keeps_private_file_mode(self):
        stream = io.BytesIO()
        member = tarfile.TarInfo("details.log")
        member.mode, member.size = 0o600, 7
        with tarfile.open(fileobj=stream, mode="w") as archive:
            archive.addfile(member, io.BytesIO(b"fixture"))
        DOCKER.extract_fixture(stream.getvalue(), self.root)
        self.assertEqual((self.root / "details.log").read_bytes(), b"fixture")
        self.assertEqual((self.root / "details.log").stat().st_mode & 0o777, 0o600)

    def test_binary_output_is_bounded_before_host_use(self):
        command = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 1024)"]
        with patch.object(self.backend, "exec_command", return_value=command):
            with self.assertRaises(ValueError):
                self.backend.read_binary("synthetic", 16, "cat", "/fixture")

    def test_binary_failure_drains_and_bounds_stderr_without_stdout(self):
        command = [sys.executable, "-c",
                   "import os; os.write(2, b'x' * 200000); os.write(1, b'synthetic stdout'); raise SystemExit(1)"]
        with patch.object(self.backend, "exec_command", return_value=command):
            with self.assertRaisesRegex(RuntimeError, "output command failed") as failure:
                self.backend.read_binary("synthetic", 1024, "cat", "/fixture")
        note = failure.exception.__notes__[0]
        self.assertIn("x" * 512, note)
        self.assertLess(len(note), 600)
        self.assertNotIn("synthetic stdout", note)

    def test_uncertain_container_start_is_owned_and_removed(self):
        failed = subprocess.CalledProcessError(1, ["docker", "run"])
        with patch.object(self.backend, "docker", side_effect=failed), \
                patch.object(DOCKER.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as remove:
            with self.assertRaises(subprocess.CalledProcessError):
                self.backend.start(self.root)
        self.assertEqual(remove.call_args.args[0][:4], ["docker", "rm", "--force", "--volumes"])
        self.assertRegex(remove.call_args.args[0][4], r"^octelium-fixture-[0-9a-f]{32}$")
        self.assertEqual(self.backend.containers, [])


if __name__ == "__main__":
    unittest.main()
