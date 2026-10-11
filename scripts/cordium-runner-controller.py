#!/usr/bin/env python3
"""Run the serial factory with private copies of projected controller credentials."""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import fcntl
import importlib.util
import json
import os
import re
import signal
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("runner", ROOT / "scripts/cordium-runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
SOURCE = Path("/var/run/cordium-runner-credentials")
STATE = Path("/data/cordium-runner")
KEYS = ("github-app-private-key", "auth-token")


def private_copies(source, destination):
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.stat().st_mode & 0o077:
        raise RuntimeError("Private credential copy directory has unsafe permissions")
    values = {}
    for key in KEYS:
        path = source / key
        if path.stat().st_mode & 0o007:
            raise RuntimeError("Projected credential must not be world-readable")
        value = path.read_bytes()
        if not value or len(value) > 4096:
            raise RuntimeError("Projected credential exceeds its declared slot")
        values[key] = value
    # Validate both files before replacing either; no source enters git or argv.
    for key, value in values.items():
        target = destination / key
        if target.exists() and target.read_bytes() == value:
            continue
        descriptor, name = tempfile.mkstemp(prefix=".credential-", dir=destination)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(value)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(0o400)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    pool = json.loads((ROOT / ".cordium/runner-pool.json").read_text())
    if pool["enabled"] is not True:
        raise RuntimeError("Controller activation remains disabled")
    checkout = runner.github_operator.command("git", "-C", str(ROOT), "rev-parse", "HEAD").decode().strip()
    runner.github_operator.verify_reviewed_main(checkout)
    version = runner.github_operator.command("cordium", "version").decode()
    if not re.search(r"(?m)^gitCommit:\s*e12b0b16d5fe94716e414fca7cfdc10b21014f2c\s*$", version):
        raise RuntimeError("Controller requires the pinned Cordium client")
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if STATE.stat().st_mode & 0o077:
        raise RuntimeError("Controller state directory has unsafe permissions")
    credentials = STATE / "credentials"
    login = STATE / "login"
    login.mkdir(mode=0o700, exist_ok=True)
    client = ["cordium", "--homedir", str(login), "--domain", "stinkyboi.com"]
    with open(STATE / "controller.lock", "a", opener=lambda path, flags: os.open(path, flags, 0o600)) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runner.serve(pool, credentials / KEYS[0], client, checkout, credentials / KEYS[1],
                     refresh_credentials=lambda: private_copies(SOURCE, credentials))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Runner controller stopped; private credential and transport output withheld") from None
