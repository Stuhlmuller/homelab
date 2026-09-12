#!/usr/bin/env python3
"""Install and operate private daily etcd backups with macOS launchd."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
import time


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("talos_etcd_backup", HERE / "talos-etcd-backup.py")
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
SNAPSHOT_NAME = re.compile(r"etcd-\d{8}T\d{6}Z-[a-z0-9_]+")
SUCCESS = "latest-success.json"
LOCK = ".schedule.lock"
LAUNCHD_LOCK_WAIT_SECONDS = 60
POLICY_SOURCE = "scripts/config/talos-etcd-backup-schedule.json"
SOURCES = ("scripts/talos-etcd-backup.py", "scripts/talos-etcd-schedule.py", POLICY_SOURCE)


def read_policy(path):
    policy = json.loads(path.read_text())
    expected = {"format", "launchd_label", "minute", "backup_interval_hours",
                "stale_after_hours", "retention_days", "minimum_valid_copies",
                "talos_client_version"}
    if set(policy) != expected or policy["format"] != 1:
        raise ValueError("unsupported schedule policy")
    for key in ("minute", "backup_interval_hours", "stale_after_hours",
                "retention_days", "minimum_valid_copies"):
        if type(policy[key]) is not int:
            raise ValueError(f"policy {key} must be an integer")
    if not (0 <= policy["minute"] < 60
            and 0 < policy["backup_interval_hours"] < policy["stale_after_hours"]
            and policy["retention_days"] >= 1 and policy["minimum_valid_copies"] >= 7
            and re.fullmatch(r"[a-z][a-z0-9.-]+", policy["launchd_label"])
            and re.fullmatch(r"v\d+\.\d+\.\d+", policy["talos_client_version"])):
        raise ValueError("invalid schedule cadence, retention, label, or client version")
    return policy


def write_file(path, contents):
    """Atomically publish a private file and persist its directory entry."""
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        backup.sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path, value):
    write_file(path, (json.dumps(value, indent=2) + "\n").encode())


def record_success(directory, completed, record):
    receipt = directory / SUCCESS
    previous = receipt.read_bytes() if receipt.exists() else None
    try:
        write_json(receipt, {"directory": completed.name, "created_at": record["created_at"],
                             "sha256": record["integrity"]["sha256"]})
    except OSError:
        # os.replace may have succeeded before its directory sync failed. Do
        # not let that visible new receipt suppress the next hourly retry.
        try:
            if previous is None:
                receipt.unlink(missing_ok=True)
                backup.sync_directory(directory)
            else:
                write_file(receipt, previous)
        except OSError:
            # If restoring the prior receipt also fails, remove the success
            # marker rather than report this attempt as confirmed.
            receipt.unlink(missing_ok=True)
            backup.sync_directory(directory)
        raise


@contextmanager
def schedule_lock(directory, shared=False, wait_seconds=0):
    # Installer creates the persistent lock; never unlink it while installed.
    with (directory / LOCK).open("rb") as stream:
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                fcntl.flock(stream, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError("scheduled backup lock is busy; retry after the running operation finishes") from None
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        yield


def created_at(record, now):
    created = datetime.fromisoformat(record["created_at"])
    if created.tzinfo is None or created > now:
        raise ValueError("backup timestamp is missing a timezone or is in the future")
    return created


def completed_directories(directory):
    return sorted((path for path in directory.iterdir() if SNAPSHOT_NAME.fullmatch(path.name)),
                  key=lambda path: path.name, reverse=True)


def latest_status(directory, policy, now):
    """Verify the newest selected artifact offline; never hide it behind an older one."""
    directories = completed_directories(directory)
    if not directories:
        return {"status": "missing"}
    newest = [path for path in directories if path.name[:21] == directories[0].name[:21]]
    # Random suffixes are not chronological. Read completion times only for
    # the newest same-second group; a corrupt older group must not block the
    # age gate and trigger a new snapshot every hour forever.
    latest = max(newest, key=lambda path: json.loads((path / backup.MANIFEST).read_text())["created_at"]) if len(newest) > 1 else newest[0]
    record = backup.verify(latest)
    age = (now - created_at(record, now)).total_seconds() / 3600
    result = {"status": "fresh", "directory": str(latest), "age_hours": age,
              "created_at": record["created_at"], "integrity": record["integrity"]}
    receipt = directory / SUCCESS
    if not receipt.exists():
        result["status"] = "unconfirmed"
    else:
        success = json.loads(receipt.read_text())
        if success != {"directory": latest.name, "created_at": record["created_at"],
                       "sha256": record["integrity"]["sha256"]}:
            result["status"] = "unconfirmed"
        elif age >= policy["stale_after_hours"]:
            result["status"] = "stale"
    return result


def prune(directory, policy, now):
    """Validate every candidate before deleting any; preserve unknown/interrupted data."""
    valid = []
    for path in completed_directories(directory):
        if path.is_symlink() or set(p.name for p in path.iterdir()) != {backup.SNAPSHOT, backup.MANIFEST}:
            raise ValueError("retention stopped: scheduled copy has unexpected entries")
        record = backup.verify(path)
        valid.append((created_at(record, now), path))
    valid.sort(reverse=True)
    removed = []
    for created, path in valid[policy["minimum_valid_copies"]:]:
        if (now - created).total_seconds() <= policy["retention_days"] * 86400:
            continue
        # Only the two verified files in this scheduled child are deletion targets.
        (path / backup.SNAPSHOT).unlink()
        (path / backup.MANIFEST).unlink()
        path.rmdir()
        removed.append(path.name)
    if removed:
        backup.sync_directory(directory)
    return removed


def run_schedule(directory, policy, talosconfig, talosctl, now=None, wait_seconds=0):
    if directory.is_symlink():
        raise ValueError("the scheduled child must not be a symlink")
    directory = backup.private_directory(directory)
    with schedule_lock(directory, wait_seconds=wait_seconds):
        now = now or datetime.now(timezone.utc)
        inspection_warning = None
        try:
            status = latest_status(directory, policy, now)
        except (OSError, ValueError, KeyError, TypeError) as error:
            # A damaged old copy or receipt must not permanently stop new
            # protection. Preserve it, create a fresh copy, and skip pruning.
            inspection_warning = str(error)
            status = {"status": "unverifiable"}
        if status["status"] == "fresh" and status["age_hours"] < policy["backup_interval_hours"]:
            return {"action": "skipped", **status}
        # Failure here leaves the previous success receipt and every older copy intact.
        completed, record = backup.backup(directory, talosconfig, talosctl)
        backup.verify(completed)
        record_success(directory, completed, record)
        # Retention runs only after both the backup and durable success receipt succeed.
        result = {"action": "backed-up", "directory": str(completed), "pruned": []}
        if inspection_warning:
            result["retention_warning"] = "Skipped because prior status was unverifiable: " + inspection_warning
        else:
            try:
                result["pruned"] = prune(directory, policy, max(now, datetime.now(timezone.utc)))
            except (OSError, ValueError, KeyError, TypeError) as error:
                result["retention_warning"] = str(error)
        return result


def durable_directory(path, create=False):
    if not path.is_absolute():
        raise ValueError("operator directories must be absolute")
    resolved = path.resolve()
    temporary_roots = (Path("/tmp").resolve(), Path("/private/var/folders"),
                       Path(tempfile.gettempdir()).resolve())
    if any(resolved == root or root in resolved.parents for root in temporary_roots):
        raise ValueError("operator runtime and backups must not depend on temporary storage")
    if create:
        resolved.mkdir(mode=0o700, parents=True, exist_ok=True)
    return backup.private_directory(resolved)


def executable(path):
    if not path.is_absolute():
        raise ValueError("client and Python paths must be absolute")
    path = path.resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("client and Python paths must name executable files")
    return path


def command(arguments, check=True):
    return subprocess.run([str(arg) for arg in arguments], capture_output=True,
                          text=True, timeout=30, check=check)


def command_failure(error, action):
    """Describe a failed command without forwarding arguments or client output."""
    operation = "local-command"
    arguments = error.cmd if isinstance(error.cmd, (list, tuple)) else []
    if action == "run":
        operation = "talos-etcd-snapshot"
    elif arguments and Path(arguments[0]).name == "launchctl":
        if len(arguments) > 1 and arguments[1] in ("print", "bootstrap", "bootout"):
            operation = "launchctl-" + arguments[1]
    result = {"action": action, "status": "failed", "operation": operation,
              "checked_at": datetime.now(timezone.utc).isoformat(),
              "prior_backups": "retained"}
    if isinstance(error, subprocess.TimeoutExpired):
        result.update(failure="timeout", timeout_seconds=error.timeout)
    else:
        result.update(failure="exit", exit_code=error.returncode)
    return result


def reviewed_sources(revision):
    root = HERE.parent
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision must be the full reviewed main commit SHA")
    if command(["git", "-C", root, "rev-parse", "HEAD"]).stdout.strip() != revision:
        raise ValueError("checkout HEAD does not match the reviewed revision")
    command(["git", "-C", root, "merge-base", "--is-ancestor", revision, "origin/main"])
    files = {}
    for name in SOURCES:
        data = command(["git", "-C", root, "show", f"{revision}:{name}"]).stdout.encode()
        if (root / name).read_bytes() != data:
            raise ValueError(f"local source differs from reviewed commit: {name}")
        files[Path(name).name] = data
    return files


def render_plist(settings, policy):
    runtime = Path(settings["runtime_directory"])
    release = runtime / "releases" / settings["revision"]
    return {"Label": policy["launchd_label"],
            "ProgramArguments": [settings["python"], str(release / "talos-etcd-schedule.py"),
                                 "run", "--runtime-directory", str(runtime), "--launchd"],
            "StartCalendarInterval": {"Minute": policy["minute"]}, "RunAtLoad": True,
            "Umask": 63, "ProcessType": "Background", "LowPriorityIO": True,
            "StandardOutPath": str(runtime / "schedule.log"),
            "StandardErrorPath": str(runtime / "schedule-error.log")}


def service_target(policy):
    return f"gui/{os.getuid()}/{policy['launchd_label']}"


def stop_loaded(policy):
    target = service_target(policy)
    if command(["/bin/launchctl", "print", target], check=False).returncode == 0:
        command(["/bin/launchctl", "bootout", target])


def replace_service(runtime, plist_path, settings, plist_bytes, policy):
    """Called with the backup lock held; restore previous state on failed handoff."""
    settings_path = runtime / "installation.json"
    old_settings = settings_path.read_bytes() if settings_path.exists() else None
    old_plist = plist_path.read_bytes() if plist_path.exists() else None
    was_loaded = command(["/bin/launchctl", "print", service_target(policy)], check=False).returncode == 0
    if was_loaded and (old_settings is None or old_plist is None):
        raise ValueError("loaded schedule has no restorable local configuration; stop before reconfiguration")
    # Retain exact previous bytes even if rollback itself encounters a disk or
    # launchctl failure. These files contain only local paths and public config.
    rollback = Path(tempfile.mkdtemp(prefix=".install-rollback-", dir=runtime))
    for name, contents in (("installation.json", old_settings), ("agent.plist", old_plist)):
        if contents is not None:
            write_file(rollback / name, contents)
    write_json(rollback / "state.json", {"was_loaded": was_loaded,
               "had_settings": old_settings is not None, "had_plist": old_plist is not None})
    backup.sync_directory(runtime)
    domain = f"gui/{os.getuid()}"
    try:
        if was_loaded:
            command(["/bin/launchctl", "bootout", service_target(policy)])
        write_json(settings_path, settings)
        write_file(plist_path, plist_bytes)
        command(["/bin/launchctl", "bootstrap", domain, plist_path])
    except (OSError, ValueError, subprocess.SubprocessError) as failure:
        errors = []
        try:
            # bootstrap may have registered/started the new child before
            # returning failure. Stop it while the installer still owns the
            # lock, so it cannot snapshot using half-restored configuration.
            stop_loaded(policy)
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError("installation failed and rollback failed: cannot stop the partially loaded "
                             f"service ({type(error).__name__}); previous configuration is retained at "
                             f"{rollback}; check local service state before retrying") from failure
        for path, contents in ((settings_path, old_settings), (plist_path, old_plist)):
            try:
                if contents is None:
                    path.unlink(missing_ok=True)
                    backup.sync_directory(path.parent)
                else:
                    write_file(path, contents)
            except OSError as error:
                errors.append(type(error).__name__)
        if was_loaded and not errors:
            try:
                command(["/bin/launchctl", "bootstrap", domain, plist_path])
            except (OSError, subprocess.SubprocessError) as error:
                errors.append(type(error).__name__)
        if errors:
            raise ValueError(f"installation failed and rollback failed ({', '.join(errors)}); "
                             f"previous configuration is retained at {rollback}; check local service state") from failure
        state = "previous loaded schedule" if was_loaded else "previous unloaded state"
        raise ValueError(f"installation failed; {state} restored; previous configuration retained at {rollback}") from failure


def install(args):
    if sys.platform != "darwin":
        raise ValueError("installation requires a logged-in macOS GUI user")
    files = reviewed_sources(args.revision)
    policy = read_policy(HERE / "config" / Path(POLICY_SOURCE).name)
    python = executable(args.python)
    talosctl = executable(args.talosctl)
    if command([talosctl, "version", "--client", "--short"]).stdout.strip() != "Client:\nTalos " + policy["talos_client_version"]:
        raise ValueError("Talos client does not match the committed version policy")
    command([python, "-c", "import sys; assert sys.version_info >= (3, 9)"])
    talosconfig = args.talosconfig.resolve(strict=True)
    if not args.talosconfig.is_absolute() or not talosconfig.is_file():
        raise ValueError("talosconfig must be an explicit absolute existing file")
    runtime = durable_directory(args.runtime_directory, create=True)
    root = durable_directory(args.backup_root)
    directory = root / "scheduled"
    if directory.is_symlink() or directory == runtime or directory in runtime.parents:
        raise ValueError("scheduled backups require their own real child directory")
    directory.mkdir(mode=0o700, exist_ok=True)
    backup.private_directory(directory)
    lock = directory / LOCK
    if not lock.exists():
        lock.touch(mode=0o600, exist_ok=False)
        backup.sync_directory(directory)
    settings = {"format": 1, "revision": args.revision, "runtime_directory": str(runtime),
                "backup_root": str(root), "talosconfig": str(talosconfig),
                "talosctl": str(talosctl), "python": str(python),
                "source_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    release = runtime / "releases" / args.revision
    plist_path = Path.home() / "Library" / "LaunchAgents" / (policy["launchd_label"] + ".plist")
    if plist_path.exists():
        previous_plist = plistlib.loads(plist_path.read_bytes())
        previous_args = previous_plist.get("ProgramArguments", [])
        try:
            previous_runtime = previous_args[previous_args.index("--runtime-directory") + 1]
        except (ValueError, IndexError):
            previous_runtime = None
        if previous_runtime != str(runtime) or previous_plist.get("Label") != policy["launchd_label"]:
            raise ValueError("this launchd label belongs to another runtime; uninstall it first")
    with schedule_lock(directory):
        previous = runtime / "installation.json"
        if previous.exists():
            previous_settings, previous_policy, _ = installed(runtime)
            if previous_settings["backup_root"] != str(root):
                raise ValueError("uninstall the old schedule and use a fresh runtime before changing its backup root")
            if previous_policy["launchd_label"] != policy["launchd_label"]:
                raise ValueError("uninstall the old schedule and use a fresh runtime before changing its launchd label")
        release.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name, data in files.items():
            path = release / name
            if path.exists() and path.read_bytes() != data:
                raise ValueError("installed release differs from reviewed source")
            write_file(path, data)
        command([python, "-c", "import pathlib,sys; [compile(pathlib.Path(p).read_text(), p, 'exec') for p in sys.argv[1:]]",
                 release / "talos-etcd-backup.py", release / "talos-etcd-schedule.py"])
        plist_bytes = plistlib.dumps(render_plist(settings, policy))
        if plistlib.loads(plist_bytes) != render_plist(settings, policy):
            raise ValueError("launchd property list round-trip failed")
        staged_plist = runtime / "validated.plist"
        write_file(staged_plist, plist_bytes)
        command(["/usr/bin/plutil", "-lint", staged_plist])
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        replace_service(runtime, plist_path, settings, plist_bytes, policy)
    return {"action": "installed", "runtime_directory": str(runtime),
            "revision": args.revision, "script": str(release / "talos-etcd-schedule.py"),
            "note": "RunAtLoad starts the first age-gated attempt; use status to verify it."}


def installed(runtime):
    runtime = durable_directory(runtime)
    settings = json.loads((runtime / "installation.json").read_text())
    if settings["format"] != 1 or settings["runtime_directory"] != str(runtime):
        raise ValueError("invalid installation record")
    release = runtime / "releases" / settings["revision"]
    for name in SOURCES:
        basename = Path(name).name
        if hashlib.sha256((release / basename).read_bytes()).hexdigest() != settings["source_sha256"][basename]:
            raise ValueError("installed source differs from its reviewed release manifest")
    policy = read_policy(release / Path(POLICY_SOURCE).name)
    directory = Path(settings["backup_root"]) / "scheduled"
    if directory.is_symlink():
        raise ValueError("the scheduled child must not be a symlink")
    directory = backup.private_directory(directory)
    return settings, policy, directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    save = commands.add_parser("install", help="install reviewed main code as a user LaunchAgent")
    save.add_argument("--revision", required=True)
    save.add_argument("--runtime-directory", type=Path, required=True)
    save.add_argument("--backup-root", type=Path, required=True)
    save.add_argument("--talosconfig", type=Path, required=True)
    save.add_argument("--talosctl", type=Path, required=True)
    save.add_argument("--python", type=Path, required=True)
    for name in ("run", "status", "uninstall"):
        sub = commands.add_parser(name)
        sub.add_argument("--runtime-directory", type=Path, required=True)
        if name == "run":
            sub.add_argument("--launchd", action="store_true",
                             help="wait up to 60 seconds for an installer-held lock")
    args = parser.parse_args()
    try:
        if args.command == "install":
            result = install(args)
        else:
            settings, policy, directory = installed(args.runtime_directory)
            if args.command == "run":
                result = run_schedule(directory, policy, Path(settings["talosconfig"]), settings["talosctl"],
                                      wait_seconds=LAUNCHD_LOCK_WAIT_SECONDS if args.launchd else 0)
            elif args.command == "status":
                with schedule_lock(directory, shared=True):
                    result = latest_status(directory, policy, datetime.now(timezone.utc))
                if sys.platform == "darwin":
                    result["launchd_loaded"] = command(["/bin/launchctl", "print", service_target(policy)], check=False).returncode == 0
                print(json.dumps({**result, "checked_at": datetime.now(timezone.utc).isoformat()}, indent=2))
                return 0 if result["status"] == "fresh" else 1
            else:
                if sys.platform != "darwin":
                    raise ValueError("uninstallation requires macOS")
                with schedule_lock(directory):
                    stop_loaded(policy)
                    plist_path = Path.home() / "Library" / "LaunchAgents" / (policy["launchd_label"] + ".plist")
                    plist_path.unlink(missing_ok=True)
                result = {"action": "uninstalled", "backups_and_runtime": "preserved"}
        print(json.dumps({**result, "checked_at": datetime.now(timezone.utc).isoformat()}, indent=2))
        return 0
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(json.dumps(command_failure(error, args.command), indent=2), file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"{datetime.now(timezone.utc).isoformat()} Schedule failed: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
