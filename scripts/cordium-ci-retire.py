#!/usr/bin/env python3
"""Retire only the dedicated Cordium CI identity after its catalog removal."""
import argparse
import json
import pathlib
import re
import subprocess
import sys

TARGETS = (
    ("IdentityProvider", "homelab-cordium-ci-oidc"),
    ("User", "homelab-cordium-ci"),
    ("Policy", "homelab-cordium-ci-execution"),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--homedir", required=True, help="Private operator admin login directory")
    parser.add_argument("--execute", action="store_true", help="Delete and verify the three fixed resources")
    args = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parent.parent
    catalog = subprocess.run(
        ["yq", "ea", "-o=json", "-I=0", "[.]", str(root / "docs/examples/octelium/homelab-services.yaml")],
        capture_output=True, text=True, check=True, timeout=15,
    )
    records = json.loads(catalog.stdout)
    if any((item.get("kind"), item.get("metadata", {}).get("name")) in TARGETS for item in records):
        raise RuntimeError("Remove the CI catalog definitions in the reviewed retirement commit first")
    if (root / ".github/workflows/cordium-check.yml").exists():
        raise RuntimeError("Remove the dispatch workflow before retiring its identity")
    client = ["octeliumctl", "--homedir", str(pathlib.Path(args.homedir).resolve()),
              "--domain", "stinkyboi.com"]

    def get(kind, name):
        result = subprocess.run(client + ["get", kind.lower(), name, "-o", "json"],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            if (re.search(r"^gRPC error NotFound:", result.stdout, re.MULTILINE)
                    or re.search(r"\bcode = NotFound\b", result.stderr)):
                return None
            raise RuntimeError(f"Cannot inspect {kind} {name}; private error output withheld")
        value = json.loads(result.stdout)
        if value.get("metadata", {}).get("name") != name:
            raise RuntimeError("Unexpected resource identity; no deletion attempted")
        return value

    if not args.execute:
        print("Dry run: retire only " + ", ".join(name for _, name in TARGETS))
        return
    # Removing the provider first prevents new logins. The workflow is already absent.
    for kind, name in TARGETS:
        if get(kind, name) is None:
            continue
        result = subprocess.run(client + ["delete", kind.lower(), name],
                                capture_output=True, text=True, timeout=30)
        if result.returncode or get(kind, name) is not None:
            raise RuntimeError(f"Retirement failed for {kind} {name}; do not claim rollback complete")
        print(f"Verified retirement: {kind} {name}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
