#!/usr/bin/env python3
"""Attempt offsite copies independently of the local etcd snapshot schedule."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys


HERE = Path(__file__).resolve().parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


local = module("local_schedule", "talos-etcd-schedule.py")
offsite = module("offsite_backup", "etcd-offsite-backup.py")
STATE = "attempt-state.json"
POLICY = "scripts/config/etcd-offsite-schedule.json"
DESTINATION = "IaC/config/etcd-backup-storage.json"
SOURCES = ("scripts/etcd-offsite-schedule.py", "scripts/etcd-offsite-backup.py",
           "scripts/talos-etcd-backup.py", "scripts/talos-etcd-schedule.py", POLICY, DESTINATION)
FAILURES = (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError)


def read_policy(path):
    value = json.loads(path.read_text())
    if (set(value) != {"format", "launchd_label", "minute", "stale_after_hours"}
            or value["format"] != 1 or value["launchd_label"] != "org.homelab.etcd-offsite"
            or type(value["minute"]) is not int or not 0 <= value["minute"] < 60
            or type(value["stale_after_hours"]) is not int or value["stale_after_hours"] < 1):
        raise ValueError("invalid committed offsite schedule policy")
    return value


def read_state(runtime):
    path = runtime / STATE
    if not path.exists():
        return {"format": 1, "pending_sha": None, "last_verified_sha": None, "last_attempt": None}
    offsite.private_file(path)
    value = json.loads(path.read_text())
    if value.get("format") != 1:
        raise ValueError("invalid attempt state")
    for key in ("pending_sha", "last_verified_sha"):
        sha = value[key]
        if sha is not None and not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("invalid attempt source SHA")
    return value


def publication_for(runtime, sha, target):
    """Adopt the single prepared pair, including a crash before state selection."""
    directory = offsite.backup.private_directory(runtime / "attempts" / sha)
    candidates = [path for path in directory.glob("publication-*")
                  if (path / offsite.RECEIPT).exists()]
    # Receipt-less partial copies cannot have reached AWS; retain them but do
    # not reuse their bytes. A damaged or ambiguous receipt must stop retries.
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError("ambiguous retained publication; inspect the private attempt")
    publication, value = offsite.load(candidates[0], target)
    if value["source_integrity"]["sha256"] != sha:
        raise ValueError("retained publication differs from its attempt SHA")
    return publication


def verified_record(publication, target, now):
    if publication is None:
        raise ValueError("verified publication is missing")
    publication, value = offsite.load(publication, target)
    if value.get("status") != "verified":
        raise ValueError("offsite pair has not passed version-specific retrieval")
    retrieved = offsite.backup.private_directory(Path(value["retrieval_directory"]))
    if retrieved.parent != publication.parent or not retrieved.name.startswith("retrieval-"):
        raise ValueError("retrieval evidence is outside the retained attempt")
    offsite.private_file(retrieved / "retrieval.json")
    evidence = json.loads((retrieved / "retrieval.json").read_text())
    if (evidence.get("format") != 1 or evidence.get("destination") != target
            or evidence.get("prefix") != value["prefix"]
            or evidence.get("objects") != value["objects"]
            or evidence.get("source_integrity") != value["source_integrity"]
            or evidence.get("offline_checksum_verified") is not True
            or any(not item["version_id"] for item in value["objects"].values())
            or any(offsite.digest(retrieved / name) != value["objects"][name]["digest"]
                   for name in offsite.FILES)):
        raise ValueError("retained version-specific retrieval evidence differs")
    record = offsite.backup.verify(publication)
    # Source age belongs to this exact published manifest, even if a later
    # local snapshot has identical snapshot bytes and a different capture time.
    created = local.created_at(record, now)
    return {"source_created_at": record["created_at"],
            "age_hours": (now - created).total_seconds() / 3600,
            "snapshot_sha256": value["source_integrity"]["sha256"],
            "version_retrieval_verified_at": evidence["verified_at"]}


def status(runtime, policy, target, now):
    state = read_state(runtime)
    result = {"status": "missing", "checked_at": now.isoformat(),
              "pending_sha": state["pending_sha"], "last_attempt": state["last_attempt"],
              "remote_alert_delivery": "unverified"}
    if state["last_verified_sha"]:
        publication = publication_for(runtime, state["last_verified_sha"], target)
        record = verified_record(publication, target, now)
        result.update(record, status="stale" if record["age_hours"] >= policy["stale_after_hours"] else "fresh")
    return result


def select_publication(runtime, settings, target, now):
    _, policy, directory = local.installed(Path(settings["local_runtime_directory"]))
    # Only verification and a private copy share the source writer's lock.
    # Offsite AWS operations use the independent retained pair after release.
    with local.schedule_lock(directory, shared=True):
        source = local.latest_status(directory, policy, now)
        if source["status"] not in ("fresh", "stale"):
            raise ValueError("latest local backup is missing or not confirmed")
        sha = source["integrity"]["sha256"]
        attempt = runtime / "attempts" / sha
        attempt.mkdir(mode=0o700, exist_ok=True)
        offsite.backup.private_directory(attempt)
        offsite.backup.sync_directory(attempt.parent)
        publication = publication_for(runtime, sha, target)
        if publication is None:
            publication = offsite.prepare(Path(source["directory"]), attempt, target)
        return sha, publication


def run_schedule(runtime, settings, policy, aws, now=None, wait_seconds=0):
    runtime = offsite.backup.private_directory(runtime)
    with local.schedule_lock(runtime, wait_seconds=wait_seconds):
        fixed_now = now is not None
        now = now or datetime.now(timezone.utc)
        state = read_state(runtime)
        operation = "source-copy"
        try:
            sha = state["pending_sha"]
            if sha:
                publication = publication_for(runtime, sha, aws.target)
                if publication is None:
                    raise ValueError("pending attempt is missing its retained publication")
            else:
                sha, publication = select_publication(runtime, settings, aws.target, now)
                state["pending_sha"] = sha
            attempt = {"started_at": now.isoformat(), "source_sha": sha, "outcome": "running"}
            state["last_attempt"] = attempt
            # Persist the selection before contacting AWS. Pending work takes
            # priority over newer local copies until this pair is verified.
            local.write_json(runtime / STATE, state)
            operation = "offsite-publication"
            _, value = offsite.load(publication, aws.target)
            action = "skipped" if value.get("status") == "verified" else "verified"
            if action == "verified":
                offsite.finish(publication, publication.parent, aws)
            record = verified_record(publication, aws.target, now)
            previous = state["last_verified_sha"]
            if previous:
                old = verified_record(publication_for(runtime, previous, aws.target), aws.target, now)
            if (not previous or datetime.fromisoformat(record["source_created_at"])
                    >= datetime.fromisoformat(old["source_created_at"])):
                state["last_verified_sha"] = sha
            state["pending_sha"] = None
            attempt.update(outcome=action, completed_at=datetime.now(timezone.utc).isoformat())
            local.write_json(publication.parent / "attempt.json", attempt)
            local.write_json(runtime / STATE, state)
        except FAILURES as error:
            # Fixed classifications only: never emit AWS output or arguments.
            failure = "timeout" if isinstance(error, subprocess.TimeoutExpired) else "operation-failed"
            state["last_attempt"] = {"started_at": now.isoformat(), "outcome": "failed",
                                     "operation": operation, "failure": failure,
                                     "completed_at": datetime.now(timezone.utc).isoformat()}
            if state["pending_sha"]:
                local.write_json(runtime / "attempts" / state["pending_sha"] / "attempt.json",
                                 state["last_attempt"])
            local.write_json(runtime / STATE, state)
            action = "failed"
        checked_at = now if fixed_now else datetime.now(timezone.utc)
        return {"action": action, **status(runtime, policy, aws.target, checked_at)}


def reviewed_sources(revision):
    root = HERE.parent
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision must be the full reviewed main commit SHA")
    if local.command(["git", "-C", root, "rev-parse", "HEAD"]).stdout.strip() != revision:
        raise ValueError("checkout HEAD differs from the reviewed revision")
    local.command(["git", "-C", root, "merge-base", "--is-ancestor", revision, "origin/main"])
    files = {}
    for name in SOURCES:
        data = local.command(["git", "-C", root, "show", f"{revision}:{name}"]).stdout.encode()
        if (root / name).read_bytes() != data:
            raise ValueError("checkout source differs from the reviewed revision")
        files[name] = data
    return files


def installed(runtime):
    runtime = local.durable_directory(runtime)
    offsite.private_file(runtime / "installation.json")
    settings = json.loads((runtime / "installation.json").read_text())
    if (settings["format"] != 1 or settings["runtime_directory"] != str(runtime)
            or not re.fullmatch(r"[0-9a-f]{40}", settings["revision"])):
        raise ValueError("invalid offsite installation record")
    release = runtime / "releases" / settings["revision"]
    for name in SOURCES:
        if hashlib.sha256((release / name).read_bytes()).hexdigest() != settings["source_sha256"][name]:
            raise ValueError("offsite installed source differs from its reviewed release")
    offsite.backup.private_directory(runtime / "attempts")
    return settings, read_policy(release / POLICY), offsite.destination(release / DESTINATION)


def render_plist(settings, policy):
    runtime = Path(settings["runtime_directory"])
    script = runtime / "releases" / settings["revision"] / SOURCES[0]
    return {"Label": policy["launchd_label"],
            "ProgramArguments": [settings["python"], str(script), "run", "--runtime-directory", str(runtime), "--launchd"],
            "StartCalendarInterval": {"Minute": policy["minute"]}, "RunAtLoad": True,
            "Umask": 63, "ProcessType": "Background", "LowPriorityIO": True,
            "StandardOutPath": str(runtime / "schedule.log"),
            "StandardErrorPath": str(runtime / "schedule-error.log")}


def install(args):
    if sys.platform != "darwin":
        raise ValueError("installation requires a logged-in macOS GUI user")
    files = reviewed_sources(args.revision)
    policy = read_policy(HERE.parent / POLICY)
    target = offsite.destination()
    python = local.executable(args.python)
    aws = offsite.AWS(args.aws_cli, args.profile, target)  # Validate inputs; no AWS call.
    local.command([python, "-c", "import sys; assert sys.version_info >= (3, 9)"])
    source_runtime = local.durable_directory(args.local_runtime_directory)
    _, _, scheduled = local.installed(source_runtime)
    runtime = local.durable_directory(args.runtime_directory, create=True)
    for directory in (source_runtime, scheduled):
        if runtime == directory or runtime in directory.parents or directory in runtime.parents:
            raise ValueError("offsite runtime must be separate from local runtime and snapshots")
    attempts = runtime / "attempts"
    attempts.mkdir(mode=0o700, exist_ok=True)
    offsite.backup.private_directory(attempts)
    lock = runtime / local.LOCK
    if not lock.exists():
        lock.touch(mode=0o600, exist_ok=False)
    offsite.backup.sync_directory(runtime)
    settings = {"format": 1, "revision": args.revision, "runtime_directory": str(runtime),
                "local_runtime_directory": str(source_runtime), "python": str(python),
                "aws_cli": str(aws.executable), "profile": args.profile,
                "source_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    plist_path = Path.home() / "Library/LaunchAgents" / (policy["launchd_label"] + ".plist")
    if plist_path.exists():
        old = plistlib.loads(plist_path.read_bytes())
        arguments = old.get("ProgramArguments", [])
        if (old.get("Label") != policy["launchd_label"] or "--runtime-directory" not in arguments
                or arguments[arguments.index("--runtime-directory") + 1:][:1] != [str(runtime)]):
            raise ValueError("offsite launchd label belongs to another runtime")
    with local.schedule_lock(runtime):
        if (runtime / "installation.json").exists():
            previous, previous_policy, _ = installed(runtime)
            if (previous["local_runtime_directory"] != str(source_runtime)
                    or previous_policy["launchd_label"] != policy["launchd_label"]):
                raise ValueError("uninstall and use a fresh runtime before changing the source or label")
        release = runtime / "releases" / args.revision
        for name, data in files.items():
            path = release / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if path.exists() and path.read_bytes() != data:
                raise ValueError("installed release differs from reviewed source")
            local.write_file(path, data)
        parents = {runtime, release.parent, release}
        for name in SOURCES:
            parents.update(parent for parent in (release / name).parents if release in parent.parents)
        for parent in sorted(parents, key=lambda path: len(path.parts), reverse=True):
            offsite.backup.sync_directory(parent)
        local.command([python, "-c", "import pathlib,sys; [compile(pathlib.Path(p).read_text(), p, 'exec') for p in sys.argv[1:]]",
                       *[release / name for name in SOURCES if name.endswith(".py")]])
        plist_bytes = plistlib.dumps(render_plist(settings, policy))
        staged_plist = runtime / "validated.plist"
        local.write_file(staged_plist, plist_bytes)
        local.command(["/usr/bin/plutil", "-lint", staged_plist])
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        local.replace_service(runtime, plist_path, settings, plist_bytes, policy)
    return {"action": "installed", "revision": args.revision,
            "note": "RunAtLoad starts an offsite attempt; verify status and the existing SSO session."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("install")
    create.add_argument("--revision", required=True)
    create.add_argument("--runtime-directory", required=True, type=Path)
    create.add_argument("--local-runtime-directory", required=True, type=Path)
    create.add_argument("--python", required=True, type=Path)
    create.add_argument("--aws-cli", required=True, type=Path)
    create.add_argument("--profile", required=True, help="existing named file-backed AWS/SSO profile")
    for name in ("run", "status", "uninstall"):
        sub = commands.add_parser(name)
        sub.add_argument("--runtime-directory", required=True, type=Path)
        if name == "run":
            sub.add_argument("--launchd", action="store_true")
    args = parser.parse_args()
    previous = os.umask(0o077)
    try:
        if args.command == "install":
            result = install(args)
        else:
            settings, policy, target = installed(args.runtime_directory)
            runtime = Path(settings["runtime_directory"])
            if args.command == "run":
                aws = offsite.AWS(Path(settings["aws_cli"]), settings["profile"], target)
                result = run_schedule(runtime, settings, policy, aws,
                                      wait_seconds=local.LAUNCHD_LOCK_WAIT_SECONDS if args.launchd else 0)
            elif args.command == "status":
                with local.schedule_lock(runtime, shared=True):
                    result = status(runtime, policy, target, datetime.now(timezone.utc))
                if sys.platform == "darwin":
                    result["launchd_loaded"] = local.command([
                        "/bin/launchctl", "print", local.service_target(policy)], check=False).returncode == 0
            else:
                if sys.platform != "darwin":
                    raise ValueError("uninstallation requires macOS")
                with local.schedule_lock(runtime):
                    local.stop_loaded(policy)
                    path = Path.home() / "Library/LaunchAgents" / (policy["launchd_label"] + ".plist")
                    path.unlink(missing_ok=True)
                result = {"action": "uninstalled", "local_schedule_and_offsite_records": "preserved"}
        print(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), **result}, indent=2))
        return 1 if (result.get("status", "fresh") != "fresh"
                     or (result.get("last_attempt") or {}).get("outcome") == "failed") else 0
    except FAILURES as error:
        note = "Retain all copies and attempt records; check local status and the existing SSO session."
        if args.command == "install" and isinstance(error, ValueError) and str(error).startswith("installation failed"):
            # The shared handoff helper reports bounded rollback state and the
            # private saved-configuration path, without command output.
            note = str(error)
        print(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(),
                          "action": args.command, "status": "failed", "note": note}),
              file=sys.stderr)
        return 1
    finally:
        os.umask(previous)


if __name__ == "__main__":
    sys.exit(main())
