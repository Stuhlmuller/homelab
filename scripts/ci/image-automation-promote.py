#!/usr/bin/env python3
"""Validate a direct promotion before a GitHub API fast-forward."""
import argparse
import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("automation", Path(__file__).with_name("image-automation.py"))
automation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(automation)


def promotion_plan(state, candidate, main_sha):
    base = candidate.get("base_sha")
    candidate_sha = candidate.get("candidate_sha")
    if main_sha == candidate_sha:
        valid, reason = automation.validate_candidate(state, candidate, base)
        return (True, "candidate is already promoted") if valid else (False, reason)
    if main_sha != base:
        return False, "main moved since candidate validation"
    return automation.validate_candidate(state, candidate, base)


def fast_forward_ref(current_sha, expected_sha, candidate_sha):
    if current_sha != expected_sha:
        return False, "compare-and-update head is stale"
    if current_sha == candidate_sha:
        return True, "already promoted"
    return True, "non-force fast-forward permitted"


def validate_candidate_paths(config, candidate, paths, symlinks=()):
    """Keep a proposal branch from smuggling unrelated files into main."""
    try:
        automation.validate(config)
    except SystemExit as error:
        return False, str(error)
    allowed = {"scripts/config/image-automation-candidate.json", "scripts/config/image-automation-state.json"}
    for consumer in config["consumers"]:
        if consumer["application_id"] == candidate.get("application") and consumer["automation_status"] == "enrolled":
            allowed.add(consumer["target"].lstrip("/"))
    if any(path not in allowed for path in paths):
        return False, "candidate tree contains an out-of-scope path"
    if symlinks:
        return False, "candidate tree contains a symlink"
    return True, "candidate tree scope valid"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--main-sha", required=True)
    parser.add_argument("--config", type=Path, default=automation.CONFIG)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--symlink", action="append", default=[])
    args = parser.parse_args()
    state = json.loads(args.state.read_text())
    candidate = json.loads(args.candidate.read_text())
    ok, reason = promotion_plan(state, candidate, args.main_sha)
    if ok and args.path:
        ok, reason = validate_candidate_paths(json.loads(args.config.read_text()), candidate, args.path, args.symlink)
    print(json.dumps({"promotable": ok, "reason": reason}))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
