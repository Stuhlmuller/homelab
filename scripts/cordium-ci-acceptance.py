#!/usr/bin/env python3
"""Observe fixed server denial cases using genuine GitHub Actions assertions."""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import argparse
import os
import pathlib
import re
import signal
import subprocess
import time

MODES = ("checks", "force-failure", "forbidden-method", "deny-ref", "deny-workflow")
REPOSITORY = "Stuhlmuller/homelab"
DENIED_REF = "refs/heads/codex/cordium-oidc-denial"


def verify_context(mode, environment):
    ref = DENIED_REF if mode == "deny-ref" else "refs/heads/main"
    workflow = "cordium-login-denial.yml" if mode == "deny-workflow" else "cordium-check.yml"
    expected = {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REPOSITORY_OWNER_ID": "252389862", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": ref,
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/.github/workflows/{workflow}@{ref}",
    }
    if (mode not in MODES or any(environment.get(key) != value for key, value in expected.items())
            or not re.fullmatch(r"[0-9a-f]{40}", environment.get("GITHUB_SHA", ""))
            or environment.get("OCTELIUM_INSECURE_TLS") == "true"
            or environment.get("OCTELIUM_AUTH_PROXY_SOCKET")):
        raise ValueError("The fixed GitHub acceptance context is required")


def is_expected_denial(result, mode, usage):
    code = "Unauthenticated" if mode == "deny-ref" else "PermissionDenied"
    description = "Octelium: Unauthorized" if mode == "forbidden-method" else ""
    raw = f"rpc error: code = {code} desc = {description}"
    formatted = raw if mode == "forbidden-method" else f"gRPC error {code}: {description}"
    # The pinned mains print one error to stdout. Cobra independently prints the
    # raw error and its own help to stderr. Reject mixed messages and HTTP/TLS
    # fallback text instead of finding an allowed substring in private output.
    return (result.returncode == 1 and result.stdout.rstrip("\n") == formatted
            and result.stderr.rstrip("\n") == ("Error: " + raw + "\n" + usage).rstrip("\n"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--verify-context", action="store_true", help="Check CI provenance without opening transport")
    parser.add_argument("--homedir", help="The fresh private CI login directory")
    parser.add_argument("--deadline", type=int, help="Enclosing CI deadline as UTC epoch seconds")
    args = parser.parse_args()
    client = []
    login_attempted = False
    outcome = 1

    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupted)
    try:
        verify_context(args.mode, os.environ)
        if args.verify_context:
            return 0
        if args.mode not in ("deny-ref", "deny-workflow", "forbidden-method"):
            raise ValueError("This probe cannot execute workspace commands")
        if not args.homedir or args.deadline is None:
            raise ValueError("Private CI directory and bounded deadline are required")
        def budget(limit):
            seconds = min(limit, args.deadline - time.time() - 60)
            if seconds <= 0:
                raise TimeoutError("No probe budget remains before cleanup")
            return seconds
        binary = "cordium" if args.mode == "forbidden-method" else "octelium"
        client = [binary, "--homedir", str(pathlib.Path(args.homedir).resolve()), "--domain", "stinkyboi.com"]
        command = ["get", "space", "--out", "json"] if args.mode == "forbidden-method" else [
            "login", "--assertion", "github-actions"]
        help_result = subprocess.run([*client, *command, "--help"], capture_output=True,
                                     text=True, timeout=budget(5), check=True)
        usage = help_result.stdout[help_result.stdout.index("Usage:\n"):]
        login_attempted = args.mode != "forbidden-method"
        result = subprocess.run([*client, *command], capture_output=True, text=True,
                                timeout=budget(60), check=False)
        if not is_expected_denial(result, args.mode, usage):
            raise RuntimeError("Expected server rejection was not established")
        print("Observed the expected server rejection; correlate the authenticated audit record")
        outcome = 0
    except (RuntimeError, ValueError, OSError, TimeoutError, subprocess.SubprocessError):
        print("Cordium acceptance failed; private client output withheld", file=sys.stderr)
    finally:
        if login_attempted:
            try:
                # The pinned logout is locally idempotent but hides remote RPC
                # failure. This is a bounded cleanup attempt, never proof that
                # an unexpectedly created server session was revoked.
                subprocess.run([*client, "logout"], capture_output=True, text=True, timeout=30, check=True)
            except (OSError, subprocess.SubprocessError):
                print("Login cleanup attempt failed; inspect the dedicated identity privately", file=sys.stderr)
                outcome = 1
    return outcome


if __name__ == "__main__":
    sys.exit(main())
