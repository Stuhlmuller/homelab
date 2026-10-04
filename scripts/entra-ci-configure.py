#!/usr/bin/env python3
"""Publish Terraform-managed Entra client IDs to protected GitHub environments."""

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
import json
from pathlib import Path
import re
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
REPO = "Stuhlmuller/homelab"
HOST_REPO = "github.com/" + REPO
ENVIRONMENTS = {"plan": "homelab-plan", "apply": "homelab-production"}


class Failure(Exception):
    """Only fixed messages may cross the private subprocess boundary."""


def command(args, operation, *, data=None):
    try:
        result = subprocess.run(args, input=data, capture_output=True, text=True,
                                check=False, timeout=120, cwd=ROOT)
    except (OSError, subprocess.SubprocessError):
        raise Failure(f"{operation} failed; private output withheld") from None
    if result.returncode:
        raise Failure(f"{operation} failed; private output withheld")
    return result.stdout


def read_json(args, operation):
    try:
        return json.loads(command(args, operation))
    except (ValueError, TypeError):
        raise Failure(f"{operation} returned invalid data; private output withheld") from None


def github(path, operation):
    return read_json(["gh", "api", "--hostname", "github.com", f"repos/{REPO}/{path}"], operation)


def verify_main():
    if command(["git", "status", "--porcelain=v1", "--untracked-files=all",
                "--ignore-submodules=none"], "checkout cleanliness"):
        raise Failure("Execution requires a clean checkout, including untracked files")
    head = command(["git", "rev-parse", "HEAD"], "checkout revision").strip()
    current = github("commits/main", "verified main lookup")
    if (not re.fullmatch(r"[0-9a-f]{40}", head) or current.get("sha") != head
            or current.get("commit", {}).get("verification", {}).get("verified") is not True):
        raise Failure("Execution requires HEAD to match GitHub's signed, verified current main")
    return head


def read_identity():
    values = read_json([
        "terragrunt", "--log-disable", "--working-dir",
        str(ROOT / "IaC/operator/azuread-ci-identities"), "output", "-json",
    ], "operator identity outputs")
    try:
        clients = values["client_ids"]["value"]
        tenant = values["tenant_id"]["value"]
        if (values["client_ids"]["sensitive"] is not True
                or values["tenant_id"]["sensitive"] is not True
                or not isinstance(clients, dict) or set(clients) != set(ENVIRONMENTS)):
            raise ValueError
        ids = [tenant, clients["plan"], clients["apply"]]
        if any(not isinstance(value, str) or str(uuid.UUID(value)) != value for value in ids):
            raise ValueError
        if any(uuid.UUID(value).int == 0 for value in ids) or len(set(ids)) != 3:
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise Failure("Operator outputs must contain sensitive, distinct canonical tenant/client UUIDs") from None
    return clients, tenant


def verify_protection(environment, document):
    try:
        rules = document["protection_rules"]
        expected_types = ["required_reviewers"] if environment == "homelab-plan" else [
            "branch_policy", "required_reviewers"]
        reviewer_rules = [rule for rule in rules if rule["type"] == "required_reviewers"]
        reviewers = reviewer_rules[0]
        branch_policy = None if environment == "homelab-plan" else {
            "protected_branches": True, "custom_branch_policies": False,
        }
        valid = (
            document["name"] == environment and document["can_admins_bypass"] is False
            and sorted(rule["type"] for rule in rules) == expected_types
            and len(reviewer_rules) == 1 and reviewers["prevent_self_review"] is False
            and [{"type": entry["type"], "id": entry["reviewer"]["id"]}
                 for entry in reviewers["reviewers"]] == [{"type": "User", "id": 57728706}]
            and document["deployment_branch_policy"] == branch_policy
        )
    except (KeyError, TypeError, IndexError):
        valid = False
    if not valid:
        raise Failure("GitHub environment protection differs from the declared owner-review policy")


def verify_destinations():
    for environment in ENVIRONMENTS.values():
        verify_protection(environment, github(f"environments/{environment}", "environment protection lookup"))
    if github("branches/main", "main protection lookup").get("protected") is not True:
        raise Failure("Production deployment requires a protected main branch")
    for environment in (None, *ENVIRONMENTS.values()):
        scope = ["--env", environment] if environment else []
        entries = read_json(["gh", "secret", "list", "--repo", HOST_REPO, *scope,
                             "--json", "name"], "GitHub credential names lookup")
        if (not isinstance(entries, list) or any(not isinstance(entry, dict)
                or not isinstance(entry.get("name"), str) for entry in entries)):
            raise Failure("GitHub credential names lookup returned invalid data")
        if any(entry["name"] == "AZUREAD_CLIENT_SECRET" for entry in entries):
            raise Failure("An AzureAD client-secret setting exists; resolve it before OIDC publication")


def publish(clients, tenant):
    for identity, environment in ENVIRONMENTS.items():
        for name, value in (("AZUREAD_CLIENT_ID", clients[identity]), ("AZUREAD_TENANT_ID", tenant)):
            command(["gh", "secret", "set", name, "--repo", HOST_REPO, "--env", environment],
                    "protected environment ID publication", data=value + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Publish four protected environment settings")
    args = parser.parse_args(argv)
    try:
        revision = verify_main() if args.execute else None
        clients, tenant = read_identity()
        verify_destinations()
        if not args.execute:
            print("Dry run passed: four Entra ID settings are ready; no GitHub settings changed.")
            return 0
        if verify_main() != revision:
            raise Failure("Current main changed during preflight; publication stopped")
        # Recheck all guards immediately before the first of the four writes.
        verify_destinations()
        publish(clients, tenant)
    except Failure as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - private API/subprocess data must never reach diagnostics.
        print("Entra CI configuration failed; private details withheld", file=sys.stderr)
        return 1
    print("Published four Entra ID settings to protected environments; no client secret created.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
