#!/usr/bin/env python3
"""Publish provider-managed Tailscale identity IDs to fixed GitHub variables."""

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Share the existing signed-main and exact owner-review protection contract.
SPEC = importlib.util.spec_from_file_location("entra_ci_guards", ROOT / "scripts/entra-ci-configure.py")
GUARDS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARDS)
BINDINGS = {
    "plan": ("homelab-plan", "TAILSCALE_CLIENT_ID"),
    "apply": ("homelab-production", "TAILSCALE_CLIENT_ID"),
    "cordium": (None, "TAILSCALE_CORDIUM_CLIENT_ID"),
}


def is_client_id(value):
    # API Key.id is an opaque string, with no documented prefix or length.
    # Bound local input size and reject whitespace, controls and secret material;
    # IDs are passed only over stdin, never interpolated into commands or URLs.
    return (isinstance(value, str) and 0 < len(value) <= 1024
            and all("!" <= char <= "~" for char in value)
            and not value.startswith("tskey-"))


def read_identity():
    values = GUARDS.read_json([
        "terragrunt", "--log-disable", "--working-dir",
        str(ROOT / "IaC/operator/tailscale-access"), "output", "-json",
    ], "Tailscale operator identity outputs")
    try:
        output = values["github_identity_client_ids"]
        clients = output["value"]
        if (set(values) != {"github_identity_client_ids"} or output["sensitive"] is not False
                or not isinstance(clients, dict) or set(clients) != set(BINDINGS)
                or any(not is_client_id(value) for value in clients.values())
                or len(set(clients.values())) != len(BINDINGS)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise GUARDS.Failure("Operator output must contain exactly three distinct non-secret Tailscale client IDs") from None
    return clients


def verify_destinations():
    for environment in GUARDS.ENVIRONMENTS.values():
        GUARDS.verify_protection(environment, GUARDS.github(
            f"environments/{environment}", "environment protection lookup"))
    if GUARDS.github("branches/main", "main protection lookup").get("protected") is not True:
        raise GUARDS.Failure("Production deployment requires a protected main branch")
    # Reject a misplaced identity selector that could mask a missing environment value.
    for environment in (None, *GUARDS.ENVIRONMENTS.values()):
        scope = ["--env", environment] if environment else []
        entries = GUARDS.read_json(["gh", "variable", "list", "--repo", GUARDS.HOST_REPO,
                                   *scope, "--json", "name"], "GitHub variable names lookup")
        forbidden = "TAILSCALE_CORDIUM_CLIENT_ID" if environment else "TAILSCALE_CLIENT_ID"
        if (not isinstance(entries, list) or any(not isinstance(item, dict)
                or not isinstance(item.get("name"), str) for item in entries)):
            raise GUARDS.Failure("GitHub variable names lookup returned invalid data")
        if any(item["name"] == forbidden for item in entries):
            raise GUARDS.Failure("A Tailscale identity variable exists outside its declared scope")


def publish(clients):
    for identity, (environment, name) in BINDINGS.items():
        scope = ["--env", environment] if environment else []
        GUARDS.command(["gh", "variable", "set", name, "--repo", GUARDS.HOST_REPO, *scope],
                       "Tailscale identity variable publication", data=clients[identity] + "\n")
    for identity, (environment, name) in BINDINGS.items():
        prefix = f"environments/{environment}/" if environment else "actions/"
        value = GUARDS.github(f"{prefix}variables/{name}", "published variable verification")
        if value.get("name") != name or value.get("value") != clients[identity]:
            raise GUARDS.Failure("Published Tailscale identity verification failed; rerun this fixed publication")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Publish the three fixed non-secret variable bindings")
    args = parser.parse_args(argv)
    try:
        revision = GUARDS.verify_main() if args.execute else None
        clients = read_identity()
        verify_destinations()
        if not args.execute:
            print("Preview passed: three Tailscale identity bindings are ready; no GitHub variables changed.")
            return 0
        if GUARDS.verify_main() != revision:
            raise GUARDS.Failure("Current main changed during preflight; publication stopped")
        verify_destinations()
        publish(clients)
    except GUARDS.Failure as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - API data and subprocess exceptions stay private.
        print("Tailscale CI configuration failed; private details withheld", file=sys.stderr)
        return 1
    print("Published and verified three Tailscale identity variables; no CI secret created.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
