#!/usr/bin/env python3
"""Export the pilot's initial credential to a new private file, never stdout."""

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PILOTS = {
    "stinkyboi": {
        "unit": "IaC/live/azuread-applications/fleet-pilot-user",
        "upn": "rodman.mac@stinkyboi.com",
    },
    "stuhlmuller": {
        "unit": "IaC/operator/entra-stuhlmuller-pilot-user",
        "upn": "rodman.mac@stuhlmuller.net",
    },
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", choices=sorted(PILOTS), default="stinkyboi")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pilot = PILOTS[args.pilot]
    destination = args.output.expanduser().absolute()
    resolved = destination.resolve()
    if (resolved.is_relative_to(ROOT)
            or any((parent / ".git").exists() for parent in resolved.parents)):
        parser.error("Credential output must be outside Git repositories")
    created = False
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "w") as output:
            result = subprocess.run([
                "terragrunt", "--log-disable", "--working-dir",
                str(ROOT / pilot["unit"]), "output", "-json",
            ], capture_output=True, check=True, timeout=120)
            values = json.loads(result.stdout)
            upn = values["user_principal_name"]["value"]
            password = values["initial_password"]["value"]
            if (upn != pilot["upn"] or not isinstance(password, str)
                    or len(password) < 32 or "\n" in password):
                raise ValueError("Invalid private output")
            output.write(
                f"Fleet Mac pilot ({args.pilot}) — native Microsoft Entra account\n\n"
                f"Sign-in: {upn}\nInitial password: {password}\n\n"
                "Use https://myaccount.microsoft.com and sign in with this work/school account.\n"
                "Change the temporary password, register Microsoft Authenticator, and complete required MFA before Platform SSO registration.\n"
                "Do not reuse or share this initial password; it becomes obsolete after the change.\n"
                "Do not enroll Company Portal into Intune. Fleet remains your MDM.\n"
            )
    except Exception:  # noqa: BLE001 - credential-bearing subprocess failures must never be logged.
        if created:
            destination.unlink(missing_ok=True)
        print("Initial credential export failed; existing files preserved and private details withheld.", file=sys.stderr)
        return 1
    print("Initial credential written to the requested private file; no credential printed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
