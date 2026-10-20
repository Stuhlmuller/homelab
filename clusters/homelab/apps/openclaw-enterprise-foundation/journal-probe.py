#!/usr/bin/env python3
"""Qualify an inactive, credential-free Enterprise journal mount."""

import fcntl
import os
import stat
import sys
import tempfile
from pathlib import Path


MOUNT = Path("/private")
DIRECTORY = "openclaw-enterprise"


class Blocked(RuntimeError):
    """A mount or lock property is unsafe for a private journal."""


def require_nfs_mount(path, mountinfo):
    matches = []
    for line in mountinfo.splitlines():
        if " - " not in line:
            continue
        left, right = line.split(" - ", 1)
        fields, source = left.split(), right.split()
        if len(fields) < 6 or len(source) < 3 or fields[4] != str(path):
            continue
        matches.append((fields[5], source[0], source[2]))
    if len(matches) != 1 or matches[0][1] not in ("nfs", "nfs4"):
        raise Blocked("journal volume is not one NFS mount")
    options = set((matches[0][0] + "," + matches[0][2]).split(","))
    if "nolock" in options or any(option.startswith("local_lock=") for option in options):
        raise Blocked("journal mount disables shared locking")


def require_private_directory(path):
    if path.is_symlink():
        raise Blocked("journal directory is a symlink")
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise Blocked("journal directory owner or mode is unsafe")


def require_lock(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise Blocked("journal lock file owner or mode is unsafe")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pid = os.fork()
        if pid == 0:
            try:
                os.close(fd)
                contender = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os._exit(0)
            except OSError:
                os._exit(2)
            os._exit(1)
        _, result = os.waitpid(pid, 0)
        if not os.WIFEXITED(result) or os.WEXITSTATUS(result) != 0:
            raise Blocked("journal lock was not exclusive across processes")
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def require_atomic_replace(directory):
    target = directory / ".delivery-probe"
    try:
        info = target.lstat()
    except FileNotFoundError:
        pass
    else:
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                stat.S_IMODE(info.st_mode) != 0o600 or
                target.read_bytes() != b"journal-mount-probe\n"):
            raise Blocked("journal probe target changed after interruption")
    fd, temporary = tempfile.mkstemp(prefix=".delivery-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(b"journal-mount-probe\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
            if target.read_bytes() != b"journal-mount-probe\n":
                raise Blocked("journal atomic write readback changed")
            target.unlink()
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def probe(mount, mountinfo):
    if not mount.is_absolute() or mount.is_symlink() or not mount.is_dir():
        raise Blocked("journal volume is absent or changed")
    require_nfs_mount(mount, mountinfo)
    directory = mount / DIRECTORY
    require_private_directory(directory)
    require_lock(directory / ".delivery.lock")
    require_atomic_replace(directory)


if __name__ == "__main__":
    try:
        probe(MOUNT, Path("/proc/self/mountinfo").read_text())
    except (Blocked, OSError, ValueError):
        print("Enterprise journal mount qualification blocked; private details withheld", file=sys.stderr)
        sys.exit(1)
    print("Enterprise journal mount local qualification passed; cross-node lock proof remains required")
