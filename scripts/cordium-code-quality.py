#!/usr/bin/env python3
"""Preview or reconcile only homelab Code Quality's runner selection."""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("runner", ROOT / "scripts/cordium-runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
ENDPOINT = "/repos/Stuhlmuller/homelab/code-quality/setup"
DESIRED = {"runner_type": "labeled", "runner_label": "cordium"}


def reconcile(api, execute=False, before_write=None):
    current = api("GET", ENDPOINT)
    if current.get("state") != "configured":
        raise RuntimeError("Code Quality is not configured; runner migration cannot enable it")
    if (current.get("runner_type") not in ("standard", "labeled")
            or not isinstance(current.get("languages"), list)
            or any(not isinstance(language, str) for language in current["languages"])
            or current.get("ai_findings_option") not in ("disabled", "on_push")):
        raise RuntimeError("Code Quality returned an unknown configuration")
    if all(current.get(key) == value for key, value in DESIRED.items()):
        return {"verified": True, "changed": False}
    if not execute:
        return {"verified": False, "changed": False, "desired": DESIRED}
    if before_write:
        before_write()
    receipt = api("PATCH", ENDPOINT, DESIRED.copy())
    actual = api("GET", ENDPOINT)
    for key in ("state", "languages", "ai_findings_option"):
        if actual.get(key) != current.get(key):
            raise RuntimeError("Code Quality configuration changed beyond runner selection; inspect before retrying")
    result = {"verified": all(actual.get(key) == value for key, value in DESIRED.items()), "changed": True}
    if "run_id" in receipt:
        if not isinstance(receipt["run_id"], int) or isinstance(receipt["run_id"], bool) or receipt["run_id"] <= 0:
            raise RuntimeError("Code Quality validation receipt is invalid; inspect before retrying")
        result["validation_run_id"] = receipt["run_id"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-key-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-sha")
    args = parser.parse_args()
    if args.execute:
        runner.github_operator.verify_reviewed_main(args.expected_sha)
        pool = json.loads((ROOT / ".cordium/runner-pool.json").read_text())
        if pool["enabled"] is not True or "cordium" not in pool["labels"]:
            raise RuntimeError("The declared Cordium pool must be enabled with the production label before migration")
    pool = json.loads((ROOT / ".cordium/runner-pool.json").read_text())
    result = reconcile(runner.installation_client(pool, args.app_key_file), args.execute,
                       before_write=lambda: runner.github_operator.verify_reviewed_main(args.expected_sha))
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Code Quality runner reconciliation failed; private authentication output withheld") from None
