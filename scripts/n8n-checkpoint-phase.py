#!/usr/bin/env python3
"""Closed n8n Application profiles and the ordinary-Terragrunt maintenance guard."""
import argparse
import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path

PHASE = "homelab.rst.io/n8n-checkpoint-phase"
SESSION = "homelab.rst.io/n8n-checkpoint-session"
APPS = ("n8n", "n8n-postgres")
PROFILES = {"n8n": ("normal", "stopped"), "n8n-postgres": ("normal", "cold", "capture")}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def profile(base, phase, session):
    app = base["metadata"]["name"]
    if phase not in PROFILES[app] or not re.fullmatch(r"[a-f0-9]{32}", session):
        raise ValueError("unknown profile or invalid session ID")
    value = copy.deepcopy(base)
    annotations = value["metadata"].setdefault("annotations", {})
    annotations.update({PHASE: phase, SESSION: session if phase != "normal" else ""})
    sources = value["spec"]["sources"]
    if app == "n8n" and phase == "stopped":
        if sources[0]["helm"].get("valuesObject"):
            raise ValueError("review new n8n Helm overrides before maintenance")
        sources[0]["helm"]["valuesObject"] = {"controllers": {"n8n": {"replicas": 0}}}
        sources[2]["path"] = "clusters/homelab/apps/n8n-maintenance"
    if app == "n8n-postgres" and phase != "normal":
        sources[0]["path"] = f"clusters/homelab/apps/n8n-postgres-{phase}"
    return value


def markers(application):
    annotations = application.get("metadata", {}).get("annotations", {})
    return {PHASE: annotations.get(PHASE, "normal"), SESSION: annotations.get(SESSION, "")}


def validate_transition(app, desired, live, session):
    current = markers(live[app])[PHASE]
    target = markers(desired)[PHASE]
    for item in live.values():
        mark = markers(item)
        if mark[PHASE] != "normal" and mark[SESSION] != session:
            raise ValueError("another maintenance session is active")
    transitions = {"n8n": {"normal": {"stopped"}, "stopped": {"normal"}},
                  "n8n-postgres": {"normal": {"cold"}, "cold": {"capture", "normal"},
                                   "capture": {"cold"}}}
    if target not in transitions[app].get(current, set()):
        raise ValueError(f"unsupported phase transition: {app} {current} -> {target}")
    if app == "n8n-postgres" and markers(live["n8n"])[PHASE] != "stopped":
        raise ValueError("n8n must remain stopped for database maintenance")
    if app == "n8n" and target == "normal" and markers(live["n8n-postgres"])[PHASE] != "normal":
        raise ValueError("resume PostgreSQL before n8n")


def load_live():
    result = subprocess.run(["kubectl", "--request-timeout=20s", "get", "applications",
                             "-n", "argocd", "-o", "json"], check=True, capture_output=True,
                            text=True, timeout=25)
    found = {x["metadata"]["name"]: x for x in json.loads(result.stdout)["items"]}
    return {name: found.get(name, {}) for name in APPS}


def check_guard(base, command, arguments, live):
    """Read-only guard. The saved-plan permit binds exact bytes and prior markers."""
    app = base["metadata"]["name"]
    if any(arg.startswith("-") and arg.lstrip("-").startswith("var") and not arg.startswith("-var-file=") for arg in arguments):
        raise ValueError("only one explicit closed -var-file= profile is supported")
    active = any(markers(item)[PHASE] != "normal" for item in live.values())
    var_files = [arg.split("=", 1)[1] for arg in arguments if arg.startswith("-var-file=")]
    if len(var_files) > 1:
        raise ValueError("additional desired-state overrides are prohibited")
    positional = [arg for arg in arguments if not arg.startswith("-") and arg != command]
    permit = None
    if command == "apply" and len(positional) == 1:
        plan = Path(positional[0])
        permit_path = Path(str(plan) + ".n8n-permit.json")
        if permit_path.is_file():
            permit = json.loads(permit_path.read_text())
            if digest(plan) != permit["plan_sha256"]:
                raise ValueError("saved plan changed after validation")
            if permit["before"] != {name: markers(item) for name, item in live.items()}:
                raise ValueError("maintenance phase changed after planning")
            var_files = [permit["var_file"]]
    if not var_files:
        if active:
            raise ValueError("n8n maintenance active; use its serial phase runner")
        return
    if command not in ("plan", "apply") or len(var_files) != 1:
        raise ValueError("maintenance permits only a single closed profile")
    if command == "apply" and permit is None:
        raise ValueError("maintenance apply requires a checked saved plan")
    path = Path(var_files[0])
    data = json.loads(path.read_text())
    note = json.loads(Path(str(path) + ".profile.json").read_text())
    if data != {"manifest": profile(base, note["phase"], note["session"])}:
        raise ValueError("profile differs from current repository desired state")
    if any(arg.startswith("-var=") or arg == "-var" for arg in arguments):
        raise ValueError("additional desired-state overrides are prohibited")
    validate_transition(app, data["manifest"], live, note["session"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command_name", choices=["guard"])
    parser.add_argument("--manifest-json", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--arguments-json", required=True)
    args = parser.parse_args()
    base = json.loads(args.manifest_json)
    if base.get("metadata", {}).get("name") not in APPS:
        return
    check_guard(base, args.command, json.loads(args.arguments_json), load_live())


if __name__ == "__main__":
    main()
