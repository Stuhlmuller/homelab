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
REPO = "https://github.com/Stuhlmuller/homelab.git"
PINNED = {"recovery-cold", "recovered"}
PROFILES = {"n8n": ("normal", "stopped", "recovered"),
            "n8n-postgres": ("normal", "cold", "capture", "recovery-cold", "recovered")}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def profile(base, phase, session, revision=None):
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
    if app == "n8n-postgres" and phase in ("cold", "capture", "recovery-cold"):
        suffix = "cold" if phase == "recovery-cold" else phase
        sources[0]["path"] = f"clusters/homelab/apps/n8n-postgres-{suffix}"
    if phase in PINNED:
        if not revision or not re.fullmatch(r"[a-f0-9]{40}", revision):
            raise ValueError("recovery requires the full prepared repository revision")
        for source in sources:
            if source.get("repoURL") == REPO:
                source["targetRevision"] = revision
    return value


def normalized_sources(sources):
    """Only chart/ref/directory default paths are computed by the owner module."""
    result = copy.deepcopy(sources)
    if len(result) > 1:
        for source in result:
            if source.get("path") in (None, "", ".") and any(
                    source.get(key) is not None for key in ("chart", "ref", "directory")):
                source.pop("path", None)
    return result


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
    transitions = {
        "n8n": {"normal": {"stopped"}, "stopped": {"recovered"}, "recovered": {"normal"}},
        "n8n-postgres": {"normal": {"cold", "recovered"}, "cold": {"capture", "recovered"},
                         "capture": {"cold", "recovery-cold"}, "recovery-cold": {"recovered"},
                         "recovered": {"normal"}},
    }
    if target not in transitions[app].get(current, set()):
        raise ValueError(f"unsupported phase transition: {app} {current} -> {target}")
    peer = markers(live["n8n" if app == "n8n-postgres" else "n8n-postgres"])[PHASE]
    if app == "n8n-postgres" and peer != ("recovered" if target == "normal" else "stopped"):
        raise ValueError("database phases require stopped n8n; unpin requires recovered n8n")
    if app == "n8n" and target == "recovered" and peer != "recovered":
        raise ValueError("recover PostgreSQL at the prepared revision before n8n")
    if app == "n8n" and target == "normal" and peer != "normal":
        raise ValueError("unpin PostgreSQL before n8n")


def load_live():
    result = subprocess.run(["kubectl", "--request-timeout=20s", "get", "applications",
                             "-n", "argocd", "-o", "json"], check=True, capture_output=True,
                            text=True, timeout=25)
    found = {x["metadata"]["name"]: x for x in json.loads(result.stdout)["items"]}
    return {name: found.get(name, {}) for name in APPS}


def check_guard(base, command, arguments, live, bound_revision=None):
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
    if note["phase"] in PINNED and note.get("revision") != bound_revision:
        raise ValueError("recovery profile is not bound to the prepared checkout revision")
    if data != {"manifest": profile(base, note["phase"], note["session"], note.get("revision"))}:
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
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1],
                              check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    check_guard(base, args.command, json.loads(args.arguments_json), load_live(), bound_revision=revision)


if __name__ == "__main__":
    main()
