#!/usr/bin/env python3
"""Verify GitHub OIDC through refreshed no-op plans of four fixed Entra units."""

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this verification with python3 -I")

import json
import os
from pathlib import Path
import re
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[2]
UNITS = ("fleet", "fleet-pilot-user", "grafana", "octelium")


class Failure(Exception):
    """Only fixed diagnostics may be published."""


def command_failure(operation, category):
    stage = operation.lower().replace(" ", "-")
    return Failure(f"ENTRA_VERIFY_FAILURE stage={stage} category={category}")


def error_category(output):
    for marker, category in (
        ("Authorization_RequestDenied", "entra-authorization-denied"),
        ("InvalidAuthenticationToken", "entra-invalid-token"),
        ("AADSTS", "entra-authentication-failed"),
        ("AccessDenied", "access-denied"),
        ("InvalidClientTokenId", "aws-invalid-credentials"),
        ("ExpiredToken", "aws-expired-credentials"),
    ):
        if marker in output:
            return category
    return "command-failed"


def command(args, operation, *, detailed_exitcode=False):
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False,
                                timeout=900, cwd=ROOT)
    except subprocess.TimeoutExpired:
        raise command_failure(operation, "timeout") from None
    except (OSError, subprocess.SubprocessError):
        raise command_failure(operation, "command-unavailable") from None
    if result.returncode == 2 and detailed_exitcode:
        raise command_failure(operation, "drift")
    if result.returncode:
        raise command_failure(operation, error_category(result.stdout + result.stderr))
    return result.stdout


def verify_context():
    expected = {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "Stuhlmuller/homelab",
        "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "ARM_USE_OIDC": "true", "ARM_USE_CLI": "false", "ARM_USE_MSI": "false",
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise Failure("Run through the exact-main Entra OIDC verification workflow")
    if (not os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")
            or not os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
            or os.environ.get("ARM_CLIENT_SECRET")):
        raise Failure("Verification requires GitHub OIDC without client-secret fallback")
    try:
        for key in ("ARM_CLIENT_ID", "ARM_TENANT_ID"):
            value = os.environ.get(key, "")
            if str(uuid.UUID(value)) != value or uuid.UUID(value).int == 0:
                raise ValueError
    except ValueError:
        raise Failure("Entra client and tenant IDs must be valid UUIDs") from None
    expected_sha = os.environ.get("EXPECTED_SHA", "")
    if (not re.fullmatch(r"[0-9a-f]{40}", expected_sha)
            or os.environ.get("GITHUB_SHA") != expected_sha):
        raise Failure("Dispatched revision does not match the reviewed main revision")
    return expected_sha


def verify_main(expected_sha):
    if command(["git", "rev-parse", "HEAD"], "checkout revision").strip() != expected_sha:
        raise Failure("Checkout differs from the reviewed main revision")
    try:
        current = json.loads(command(["gh", "api", "--hostname", "github.com",
                                     "repos/Stuhlmuller/homelab/commits/main"], "current main lookup"))
        valid = (current["sha"] == expected_sha and current["commit"]["verification"]["verified"] is True)
    except (ValueError, TypeError, KeyError):
        valid = False
    if not valid:
        raise Failure("Verification requires the signed, verified current main revision")


def main():
    try:
        expected_sha = verify_context()
        verify_main(expected_sha)
        if command(["git", "status", "--porcelain=v1", "--untracked-files=all",
                    "--ignore-submodules=none"], "checkout cleanliness"):
            raise Failure("Verification requires a clean checkout")
        command(["terragrunt", "--working-dir", str(ROOT / "IaC"), "stack", "generate"], "stack generation")
        for unit in UNITS:
            verify_main(expected_sha)
            # No targeting, refresh-only mode, saved plan, locking or apply:
            # every configured resource is refreshed and desired drift fails.
            command([
                "terragrunt", "--log-disable", "--working-dir",
                str(ROOT / "IaC/live/azuread-applications" / unit),
                "run", "--source-update", "--", "plan", "-input=false", "-lock=false",
                "-refresh=true", "-detailed-exitcode", "-no-color",
            ], f"Entra unit {unit}", detailed_exitcode=True)
            print(f"Entra unit {unit}: refreshed no-op plan verified")
        verify_main(expected_sha)
    except Failure as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - never disclose private subprocess/API responses.
        print("Entra OIDC verification failed; private details withheld", file=sys.stderr)
        return 1
    print("All four Entra units verified without applying changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
