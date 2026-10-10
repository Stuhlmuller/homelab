#!/usr/bin/env python3
"""Verify the active CI mesh identity and its Kubernetes authorization boundary."""
import argparse
import json
import subprocess
import sys

SERVER = "https://homelab-tailscale-operator.tail67beb.ts.net"
DENIAL = "The homelab CI plan identity may only perform dry-run writes."


class Failure(Exception):
    pass


def command(args):
    try:
        return subprocess.run(["kubectl", "--request-timeout=15s", *args],
                              capture_output=True, text=True, check=False, timeout=25)
    except (OSError, subprocess.SubprocessError):
        raise Failure("Kubernetes identity check failed; private output withheld") from None


def checked(args):
    result = command(args)
    if result.returncode:
        raise Failure("Kubernetes identity check failed; private output withheld")
    return result.stdout


def verify(identity):
    config = json.loads(checked(["config", "view", "--minify", "-o", "json"]))
    if (len(config["clusters"]) != 1 or config["clusters"][0]["cluster"] != {"server": SERVER}
            or len(config["users"]) != 1 or config["users"][0].get("user", {}) != {}):
        raise Failure("CI kubeconfig must use the fixed verified mesh endpoint without bearer credentials")
    who = json.loads(checked(["auth", "whoami", "-o", "json"]))
    groups = who["status"]["userInfo"]["groups"]
    if (not isinstance(groups, list) or "system:masters" in groups
            or [group for group in groups if group.startswith("tag:")] != [f"tag:homelab-ci-{identity}"]):
        raise Failure("The API proxy did not impersonate the expected scoped CI identity")
    checked(["-n", "argocd", "get", "application", "tailscale", "-o", "name"])
    # Empty JSON Patch deliberately carries no mutation, even if the denial guard
    # is missing. A dry-run-only result is insufficient proof of write isolation.
    patch = ["-n", "argocd", "patch", "application", "tailscale", "--type=json", "--patch=[]", "-o", "name"]
    checked([*patch, "--dry-run=server"])
    if identity == "plan":
        result = command(patch)
        if (result.returncode == 0 or DENIAL not in result.stderr
                or "homelab-ci-plan-dry-run" not in result.stderr):
            raise Failure("Expected plan write admission denial was not established; no-op patch carried no changes")
    elif checked(["auth", "can-i", "*", "*", "--all-namespaces"]).strip() != "yes":
        raise Failure("Protected apply identity lacks its declared cluster administration permission")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("identity", choices=("plan", "apply"))
    args = parser.parse_args(argv)
    try:
        verify(args.identity)
    except Failure as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - kubeconfig and API content must not reach public logs.
        print("Kubernetes identity response was invalid; private output withheld", file=sys.stderr)
        return 1
    print("Scoped mesh identity and Kubernetes access boundary verified; private output withheld.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
