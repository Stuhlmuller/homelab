#!/usr/bin/env python3
"""Run the serial factory with private copies of projected controller credentials."""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import fcntl
import importlib.util
import json
import math
import os
import re
import signal
from pathlib import Path
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("runner", ROOT / "scripts/cordium-runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
SOURCE = Path("/var/run/cordium-runner-credentials")
STATE = Path("/data/cordium-runner")
KEYS = ("github-app-private-key", "auth-token")
# Bounds cover existing command timeouts, startup/deletion loops and the job deadline.
HEALTH_BUDGET = {"poll": 600, "provision": 840, "runner": runner.RUNNER_EXEC_TIMEOUT + 60,
                 "cleanup": 600, "idle": 90}
REPOSITORY = "https://github.com/Stuhlmuller/homelab.git"
SOURCE_PATHS = (
    ".cordium", "builds/cordium-runner/Dockerfile", "builds/cordium-runner/Dockerfile.controller", "scripts/cordium-runner-controller.py",
    "scripts/cordium-runner.py", "scripts/policy-bot-webhook.py", "scripts/cordium-ci-acceptance.py",
    "scripts/ci/cordium-runner-probe.sh", "scripts/ci/install-cordium-client.sh", "scripts/ci/install-octelium-client.sh",
)


def reviewed_controller_main(source, repository):
    command = runner.github_operator.command
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise RuntimeError("Controller source requires an exact image revision")
    if command("git", "-C", str(ROOT), "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"):
        raise RuntimeError("Controller image source is dirty")
    if command("git", "-C", str(ROOT), "rev-parse", "HEAD").decode().strip() != source:
        raise RuntimeError("Controller source differs from its image revision")
    # Fetch only into private state; never execute fetched code or modify the image.
    if not repository.exists():
        command("git", "clone", "--bare", "--no-hardlinks", str(ROOT), str(repository))
    shallow = command("git", "-C", str(repository), "rev-parse", "--is-shallow-repository").decode().strip() == "true"
    command("git", "-C", str(repository), "fetch", "--no-tags", *(["--unshallow"] if shallow else []),
            REPOSITORY, "refs/heads/main")
    current = command("git", "-C", str(repository), "rev-parse", "FETCH_HEAD").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", current):
        raise RuntimeError("Current main revision is invalid")
    command("git", "-C", str(repository), "merge-base", "--is-ancestor", source, current)
    command("git", "-C", str(repository), "diff", "--exit-code", source, current, "--", *SOURCE_PATHS)
    return current


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


def process_start(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
    if fields[0] == "Z":
        raise RuntimeError("Controller process exited")
    return fields[19]


def health_progress(phase):
    receipt = {"pid": os.getpid(), "start": process_start(os.getpid()), "phase": phase,
               "deadline": time.monotonic() + HEALTH_BUDGET[phase]}
    descriptor, name = tempfile.mkstemp(prefix=".health-", dir=STATE)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(receipt, output)
        os.replace(temporary, STATE / "health.json")
    finally:
        temporary.unlink(missing_ok=True)


def healthcheck():
    receipt = json.loads((STATE / "health.json").read_text())
    if (set(receipt) != {"pid", "start", "phase", "deadline"}
            or type(receipt["pid"]) is not int or receipt["pid"] <= 0
            or receipt["phase"] not in HEALTH_BUDGET
            or type(receipt["deadline"]) not in (float, int) or not math.isfinite(receipt["deadline"])
            or not 0 < receipt["deadline"] - time.monotonic() <= HEALTH_BUDGET[receipt["phase"]]
            or process_start(receipt["pid"]) != receipt["start"]):
        raise RuntimeError("Controller progress is stale or invalid")
    with (STATE / "controller.lock").open("r") as lock:
        if json.load(lock) != [receipt["pid"], receipt["start"]]:
            raise RuntimeError("Controller receipt belongs to a previous lock owner")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
    raise RuntimeError("Controller does not own its lifecycle lock")


def main():
    pool = json.loads((ROOT / ".cordium/runner-pool.json").read_text())
    if pool["enabled"] is not True:
        raise RuntimeError("Controller activation remains disabled")
    checkout = runner.github_operator.command("git", "-C", str(ROOT), "rev-parse", "HEAD").decode().strip()
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
        lock.seek(0)
        lock.truncate()
        json.dump([os.getpid(), process_start(os.getpid())], lock)
        lock.flush()
        (STATE / "health.json").unlink(missing_ok=True)
        try:
            runner.serve(pool, credentials / KEYS[0], client, checkout, credentials / KEYS[1],
                         refresh_credentials=lambda: private_copies(SOURCE, credentials),
                         reviewed_main=lambda: reviewed_controller_main(checkout, STATE / "source.git"),
                         progress=health_progress)
        finally:
            (STATE / "health.json").unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--healthcheck"]:
            healthcheck()
        elif len(sys.argv) == 1:
            main()
        else:
            raise RuntimeError("Unsupported controller arguments")
    except Exception:
        raise SystemExit("Runner controller stopped; private credential and transport output withheld") from None
