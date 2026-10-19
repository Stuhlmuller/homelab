#!/usr/bin/env python3
"""Create and attest the fixed, non-secret OCE startup candidate on reviewed main.

Only the protected workflow may execute this one-time Kubernetes create. The
application remains unregistered; this script never updates an existing Secret.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "clusters/homelab/apps/openclaw-enterprise"
NAMESPACE = "openclaw-system"
DIGEST = "980de11bbc688a33741a19c9093f613e74e464d2aae897571ac61d0056593c71"
NAME = "occ-installation-startup-" + DIGEST[:32]
KUBE_SERVER = "https://kubernetes-api-ci.stinkyboi.com"
REPOSITORY = "https://github.com/Stuhlmuller/homelab.git"
SHA = re.compile(r"[0-9a-f]{40}\Z")


class Blocked(RuntimeError):
    """Unexpected source, cluster, or CI state: do not create anything."""


def command(args, *, data=None):
    try:
        result = subprocess.run(args, input=data, text=True, capture_output=True,
                                timeout=30, cwd=ROOT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Blocked(f"{args[0]} command unavailable") from exc
    if result.returncode:
        # Kubernetes errors and remote URLs can contain private details.
        raise Blocked(f"{args[0]} command failed")
    return result.stdout


def source_contract():
    candidate = (APP / "installation.yaml").read_bytes()
    if not candidate or hashlib.sha256(candidate).hexdigest() != DIGEST:
        raise Blocked("reviewed Installation bytes changed")
    try:
        values = json.loads(command(["yq", "-o=json", ".", str(APP / "values.yaml")]))
        config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
    except (ValueError, KeyError, TypeError) as exc:
        raise Blocked("startup source contract is invalid") from exc
    if (values.get("installation", {}).get("secretName") != NAME or
            values["installation"].get("key") != "installation.yaml" or
            values.get("controlPlane", {}).get("installationChecksum") != DIGEST or
            config.get("activationEnabled") is not False or
            config.get("installationPhase") != "unselected"):
        raise Blocked("chart or activation contract changed")
    return candidate


def reviewed_main(expected):
    if (not SHA.fullmatch(expected) or os.environ.get("GITHUB_ACTIONS") != "true" or
            os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch" or
            os.environ.get("GITHUB_REF") != "refs/heads/main" or
            os.environ.get("GITHUB_SHA") != expected):
        raise Blocked("protected exact-main dispatch is required")
    if command(["git", "status", "--porcelain=v1", "--untracked-files=all",
                "--ignore-submodules=none"]).strip():
        raise Blocked("reviewed checkout is not clean")
    if command(["git", "rev-parse", "HEAD"]).strip() != expected:
        raise Blocked("checkout differs from dispatch")
    remote = command(["git", "ls-remote", REPOSITORY, "refs/heads/main"]).split()
    if len(remote) != 2 or remote[0] != expected or remote[1] != "refs/heads/main":
        raise Blocked("remote main advanced")


def kube(*args, data=None):
    return command(["kubectl", "--request-timeout=15s", *args], data=data)


def kube_json(*args):
    result = kube(*args).strip()
    try:
        return json.loads(result) if result else None
    except ValueError as exc:
        raise Blocked("Kubernetes returned invalid JSON") from exc


def desired_secret(candidate):
    return {
        "apiVersion": "v1", "kind": "Secret",
        "metadata": {
            "name": NAME, "namespace": NAMESPACE,
            "labels": {"app.kubernetes.io/part-of": "openclaw-enterprise"},
            "annotations": {"homelab.stuhlmuller.dev/installation-sha256": DIGEST},
        },
        "type": "Opaque", "immutable": True,
        "data": {"installation.yaml": base64.b64encode(candidate).decode("ascii")},
    }


def verify_secret(actual, candidate):
    if not isinstance(actual, dict):
        raise Blocked("startup Secret is absent")
    metadata = actual.get("metadata", {})
    if (actual.get("kind") != "Secret" or actual.get("type") != "Opaque" or
            actual.get("immutable") is not True or
            metadata.get("name") != NAME or metadata.get("namespace") != NAMESPACE or
            metadata.get("ownerReferences") or
            metadata.get("annotations", {}).get(
                "homelab.stuhlmuller.dev/installation-sha256") != DIGEST or
            set(actual.get("data", {})) != {"installation.yaml"}):
        raise Blocked("startup Secret is mutable or foreign")
    try:
        installed = base64.b64decode(actual["data"]["installation.yaml"], validate=True)
    except (ValueError, TypeError, base64.binascii.Error) as exc:
        raise Blocked("startup Secret data is invalid") from exc
    if installed != candidate:
        raise Blocked("startup Secret differs from reviewed candidate")


def execute(expected, candidate):
    reviewed_main(expected)
    context = kube_json("config", "view", "--minify", "-o=json")
    if (not isinstance(context, dict) or
            len(context.get("clusters", [])) != 1 or
            context["clusters"][0].get("cluster", {}).get("server") != KUBE_SERVER):
        raise Blocked("protected Kubernetes endpoint changed")
    namespace = kube_json("get", "namespace", NAMESPACE, "-o=json")
    if (not isinstance(namespace, dict) or
            namespace.get("metadata", {}).get("labels", {}).get(
                "app.kubernetes.io/part-of") != "openclaw-enterprise"):
        raise Blocked("Enterprise foundation namespace is absent or foreign")
    args = ("get", "secret", NAME, "-n", NAMESPACE, "--ignore-not-found", "-o=json")
    existing = kube_json(*args)
    if existing is None:
        # Create only: an existing, differing Secret is never patched or deleted.
        try:
            kube("create", "-f", "-", data=json.dumps(desired_secret(candidate)))
        except Blocked:
            # The API may have accepted a create before the response was lost.
            existing = kube_json(*args)
            if existing is None:
                raise
    if existing is not None:
        verify_secret(existing, candidate)
    verify_secret(kube_json(*args), candidate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-sha")
    args = parser.parse_args()
    try:
        candidate = source_contract()
        if args.execute:
            execute(args.expected_sha or "", candidate)
        elif args.expected_sha:
            raise Blocked("--expected-sha applies only to --execute")
    except (Blocked, OSError) as exc:
        print(f"OpenClaw Enterprise startup blocked: {exc}", file=sys.stderr)
        return 1
    print(f"Reviewed immutable startup candidate {NAME} ({DIGEST})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
