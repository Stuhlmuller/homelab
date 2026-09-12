#!/usr/bin/env python3
"""Run the repository gate in an owned, disposable Cordium workspace."""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import argparse
import json
import pathlib
import re
import signal
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", required=True, help="Exact reviewed 40-character commit SHA")
    parser.add_argument("--homedir", required=True, help="Private Octelium login directory")
    parser.add_argument("--deadline", required=True, type=int,
                        help="Enclosing CI execution deadline as UTC epoch seconds")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.checkout):
        parser.error("--checkout must be a full lowercase commit SHA")
    root = pathlib.Path(__file__).resolve().parent.parent
    client = ["cordium", "--homedir", str(pathlib.Path(args.homedir).resolve()),
              "--domain", "stinkyboi.com"]
    workspace = None
    creation_attempted = False
    result = 1
    # The workflow captures this deadline before Nix and transport setup.
    # Reserve two minutes for deletion/verification and one for wrapper logout.
    work_deadline = time.monotonic() + args.deadline - time.time() - 180

    def call(*command, timeout=60, capture=False, deadline=None):
        seconds_left = (work_deadline if deadline is None else deadline) - time.monotonic()
        if seconds_left <= 0:
            raise TimeoutError("Cordium execution budget exhausted; preserving cleanup time")
        return subprocess.run(client + list(command), timeout=min(timeout, seconds_left),
                              capture_output=capture, text=True, check=True)

    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupted)
    try:
        existing = json.loads(call("get", "workspace", "--out", "json", capture=True).stdout)
        if existing.get("items"):
            raise RuntimeError("Dedicated CI identity has retained workspaces; inspect them before retrying")
        # --start suppresses JSON in the pinned CLI, so create and start separately.
        creation_attempted = True
        created = call("create", "workspace", "--file", str(root / ".cordium/workspace.yaml"),
                       "--checkout", args.checkout, "--ephemeral", "--out", "json", capture=True)
        candidate = json.loads(created.stdout)["metadata"]["name"]
        if not isinstance(candidate, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", candidate):
            raise ValueError("Cordium returned an invalid workspace name")
        workspace = candidate
        print(f"Cordium workspace: {workspace}; checkout: {args.checkout}", flush=True)
        call("start", workspace)
        deadline = min(work_deadline, time.monotonic() + 300)
        while time.monotonic() < deadline:
            state = json.loads(call("get", "workspace", workspace, "--out", "json",
                                    capture=True, deadline=deadline).stdout)["status"]["state"]
            if state == "RUNNING":
                break
            if state in ("STOPPED", "FAILED"):
                raise RuntimeError(f"Workspace did not start: {state}")
            time.sleep(min(5, max(0, deadline - time.monotonic())))
        else:
            raise TimeoutError("Workspace was not ready within the five-minute startup budget")
        actual = call("exec", workspace, "--no-stdin", "--workdir", "/workspace/repo", "--",
                      "git", "rev-parse", "HEAD", capture=True).stdout.strip()
        if actual != args.checkout:
            raise RuntimeError("Remote checkout does not match the reviewed commit")
        call("exec", workspace, "--no-stdin", "--root", "--workdir", "/workspace/repo", "--",
             "nix", "--extra-experimental-features", "nix-command flakes", "develop",
             "--command", "bash", "scripts/ci/static-checks.sh", timeout=1200)
        result = 0
    except subprocess.CalledProcessError as error:
        result = error.returncode if error.returncode > 0 else 1
        print(f"Cordium operation failed with exit {result}", file=sys.stderr)
    except (ValueError, KeyError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
    finally:
        if workspace:
            try:
                cleanup_deadline = time.monotonic() + 120
                call("delete", "workspace", workspace, deadline=cleanup_deadline)
                deadline = min(cleanup_deadline, time.monotonic() + 60)
                while True:
                    seconds_left = deadline - time.monotonic()
                    if seconds_left <= 0:
                        raise RuntimeError("Deleted workspace is still listed after one minute")
                    remaining = json.loads(call("get", "workspace", "--out", "json",
                                                capture=True, timeout=15, deadline=deadline).stdout)
                    if not any(item["metadata"]["name"] == workspace for item in remaining.get("items", [])):
                        break
                    time.sleep(min(2, max(0, deadline - time.monotonic())))
                print(f"Verified deletion of disposable workspace: {workspace}", flush=True)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, KeyError, RuntimeError, TimeoutError) as error:
                print(f"Cleanup failed for {workspace}: {error}", file=sys.stderr)
                result = result or 1
        elif creation_attempted:
            print("Creation result unknown; inspect this dedicated CI identity before retrying", file=sys.stderr)
    return result


if __name__ == "__main__":
    sys.exit(main())
