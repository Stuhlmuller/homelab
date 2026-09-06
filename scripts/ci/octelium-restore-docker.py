#!/usr/bin/env python3
"""Host orchestration for synthetic fixtures; never mount production data or sockets."""
import importlib.util
import io
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import tarfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
PG_COMMANDS = {"initdb", "pg_ctl", "createdb", "psql", "pg_dumpall", "pg_dump", "pg_restore"}
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_FILES = 128 * 1024 * 1024  # Same bound as the synthetic container tmpfs.


def extract_fixture(raw, destination):
    """Extract only bounded regular fixture files/directories into private scratch."""
    if len(raw) > MAX_ARCHIVE:
        raise ValueError("Synthetic output archive exceeds its bound")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        members, size = [], 0
        for member in archive:
            path = Path(member.name)
            size += member.size
            if (path.is_absolute() or ".." in path.parts
                    or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE)
                    or member.sparse is not None
                    or member.size < 0 or size > MAX_FILES or len(members) >= 8192):
                raise ValueError("Synthetic output archive violates its file contract")
            members.append(member)
        archive.extractall(destination, members=members, filter="data")


def load_boundary():
    spec = importlib.util.spec_from_file_location("fixture_boundary", ROOT / "scripts/ci/restore-egress-check.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DockerFixtures:
    pg_commands = PG_COMMANDS

    def __init__(self, image_id, probe):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise ValueError("Fixtures require an immutable tested Docker config ID")
        self.image_id = image_id
        self.probe = Path(probe).resolve(strict=True)
        if not self.probe.is_file():
            raise ValueError("Synthetic network probe must be a regular file")
        self.boundary = load_boundary()
        self.containers = []
        self.source = None
        self.restore = None
        self.work = None

    def docker(self, *command, **kwargs):
        return subprocess.run(command, check=True, text=True, capture_output=True, timeout=90, **kwargs)

    def start_container(self, mounts=()):
        name = "octelium-fixture-" + uuid.uuid4().hex
        # Record before creation so an uncertain docker-run failure is cleaned up.
        self.containers.append(name)
        command = [*self.boundary.runtime_options(), "--detach", "--name", name,
                   "--mount", f"type=bind,src={self.probe},dst=/tests/probe,readonly"]
        for mount in mounts:
            command.extend(("--mount", mount))
        # ENTRYPOINT is the launcher; no shell or PG process starts unfiltered.
        self.docker(*command, self.image_id, "/bin/sh", "-c", "while :; do sleep 30; done")
        return name

    def exec_command(self, container, *command):
        # docker exec does not inherit PID1's seccomp filter. Re-enter explicitly.
        return ["docker", "exec", container, self.boundary.LAUNCHER, *command]

    def execute(self, container, *command, check=True, **kwargs):
        return subprocess.run(self.exec_command(container, *command),
                              check=check, text=True, capture_output=True, timeout=90, **kwargs)

    def read_binary(self, container, limit, *command):
        # Docker cp cannot reliably read tmpfs. Stream through a filtered exec,
        # bounding bytes and elapsed time before accepting anything on the host.
        process = subprocess.Popen(self.exec_command(container, *command),
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        output = bytearray()
        deadline = time.monotonic() + 90
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
                    raise TimeoutError("Synthetic fixture output timed out")
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > limit:
                    raise ValueError("Synthetic fixture output exceeds its bound")
            if process.wait(timeout=max(0.001, deadline - time.monotonic())):
                raise RuntimeError("Synthetic fixture output command failed")
            return bytes(output)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()

    def start(self, root):
        self.root = Path(root)
        try:
            self.source = self.start_container()
            self.execute(self.source, "mkdir", "/work/socket")
        except BaseException:
            self.close()
            raise

    def run(self, *args, **kwargs):
        if args[0] not in PG_COMMANDS:
            raise ValueError("Only declared PostgreSQL fixture commands may be routed")
        if self.work is not None and any(str(self.work) in str(arg) for arg in args):
            container, host_root = self.restore, self.work
        else:
            container, host_root = self.source, self.root
        command = [str(arg).replace(str(host_root), "/work") for arg in args]
        if args[0] == "pg_dump":
            target = Path(args[args.index("--file") + 1])
            remote = str(target).replace(str(self.root), "/work")
            self.execute(container, "mkdir", "-p", str(Path(remote).parent))
            result = self.execute(container, *command, **kwargs)
            target.write_bytes(self.read_binary(container, 16 * 1024 * 1024, "cat", remote))
            target.chmod(0o600)
            return result
        return self.execute(container, *command, **kwargs)

    def drill(self, backups, work, script):
        # These files were generated from inert fixture rows on this host. The
        # container mount, not mode bits, enforces read-only source access.
        for path in backups.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o444)
        backups.chmod(0o755)
        self.work = Path(work)
        self.restore = self.start_container((
            f"type=bind,src={backups},dst=/backup,readonly",
            f"type=bind,src={script},dst=/tests/restore-drill.sh,readonly",
        ))
        result = self.execute(self.restore, "/bin/sh", "/tests/restore-drill.sh", "/backup", "/work", check=False)
        # Keep the filtered fixture container alive for locale inspection. tmpfs
        # disappears with its container; copy only synthetic results for assertions.
        raw = self.read_binary(self.restore, MAX_ARCHIVE, "tar", "-C", "/work", "-cf", "-", ".")
        extract_fixture(raw, work)
        return result

    def finish_case(self):
        if self.restore is not None:
            self.docker("docker", "rm", "--force", self.restore)
            self.containers.remove(self.restore)
            self.restore = None
            self.work = None

    def close(self):
        failures = []
        for name in reversed(self.containers):
            try:
                result = subprocess.run(["docker", "rm", "--force", name], text=True,
                                        capture_output=True, timeout=30, check=False)
            except (OSError, subprocess.TimeoutExpired):
                failures.append(name)
                continue
            if result.returncode and "No such container" not in result.stderr:
                failures.append(name)
        self.containers = failures
        if failures:
            raise RuntimeError("Synthetic fixture container cleanup failed")
