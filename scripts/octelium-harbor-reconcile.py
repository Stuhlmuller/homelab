#!/usr/bin/env python3
"""Inspect or reconcile only Harbor's native-authenticated Octelium transport."""
import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
import importlib.util
import json
import pathlib
import re
import signal
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAME = "harbor.default"


def run(*command, **kwargs):
    return subprocess.run(command, capture_output=True, text=True, timeout=45, check=True, **kwargs)


def verify_reviewed_main(expected):
    if not expected or not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise RuntimeError("Execution requires the full reviewed main SHA")
    if run("git", "-C", str(ROOT), "status", "--porcelain=v1", "--untracked-files=all",
           "--ignore-submodules=none").stdout:
        raise RuntimeError("Execution requires a clean checkout")
    head = run("git", "-C", str(ROOT), "rev-parse", "HEAD").stdout.strip()
    remote = run("git", "ls-remote", "https://github.com/Stuhlmuller/homelab.git",
                 "refs/heads/main").stdout.split()[0]
    if head != expected or remote != expected:
        raise RuntimeError("Checkout and remote main must match the reviewed SHA")
    run("git", "-C", str(ROOT), "cat-file", "-e", "HEAD:scripts/octelium-harbor-reconcile.py")


def valid_contract(service):
    spec = service.get("spec", {})
    config = spec.get("config", {})
    header = config.get("http", {}).get("header", {})
    return (service.get("kind") == "Service"
            and service.get("metadata", {}).get("name") in ("harbor", NAME)
            and spec.get("isPublic") is True and spec.get("isAnonymous") is True
            and spec.get("mode") == "WEB" and spec.get("port") == 80
            and config.get("upstream", {}).get("url") ==
            "https://istio-ingressgateway.istio-system.svc.cluster.local:443"
            and header.get("authorizationMode") == "PASS"
            and header.get("host", {}).get("value") == "harbor.stinkyboi.com")


def declared_service():
    result = run("yq", "ea", "-o=json", "-I=0",
                 'select(.kind == "Service" and .metadata.name == "harbor")',
                 str(ROOT / "docs/examples/octelium/homelab-services.yaml"))
    desired = json.loads(result.stdout)
    if not valid_contract(desired):
        raise RuntimeError("Harbor must retain its exact native-authentication transport contract")
    return {**desired, "metadata": {**desired["metadata"], "name": NAME}}


def reconcile(client, environment, desired, directory, execute):
    def current():
        try:
            result = run(*client, "get", "service", NAME, "-o", "json", env=environment)
        except subprocess.CalledProcessError as error:
            if (re.search(r"^gRPC error NotFound:", error.stdout or "", re.MULTILINE)
                    or re.search(r"\bcode = NotFound\b", error.stderr or "")):
                return None
            raise RuntimeError("Native read failed; absence is not established") from None
        value = json.loads(result.stdout)
        if value.get("metadata", {}).get("name") != NAME:
            raise RuntimeError("Unexpected Service identity")
        return value

    before = current()
    print("Harbor Service present:", before is not None)
    print("Harbor transport contract matches:", before is not None and valid_contract(before))
    if not execute:
        return
    manifest = directory / "harbor.json"
    manifest.write_text(json.dumps(desired))
    manifest.chmod(0o600)
    for _ in range(2):
        result = run(*client, "apply", "--include", "Service", str(manifest), env=environment)
        if re.search(r"Could not (list|create|update|apply)|gRPC error", result.stdout + result.stderr):
            raise RuntimeError("Native apply reported a failure")
    if "No applied changes in Cluster Core resources" not in result.stdout:
        raise RuntimeError("Repeated apply did not converge")
    after = current()
    if after is None or not valid_contract(after):
        raise RuntimeError("Harbor transport contract did not converge")
    print("Verified Harbor transport convergence; Harbor authenticates registry clients")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--homedir", help="Existing private Octelium operator login directory")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda signum, _: sys.exit(128 + signum))
    if args.execute:
        verify_reviewed_main(args.expected_sha)
    # Reuse the already pinned TLS carrier and client validation. Import only
    # after the execution guard; no native credentials are copied or persisted.
    source = importlib.util.spec_from_file_location("native_transport", ROOT / "scripts/octelium-nofx-reconcile.py")
    helper = importlib.util.module_from_spec(source)
    source.loader.exec_module(helper)
    desired = declared_service()
    client = [helper.verified_client(), "--domain", "stinkyboi.com"]
    if args.homedir:
        client += ["--homedir", str(pathlib.Path(args.homedir).resolve())]
    with tempfile.TemporaryDirectory(prefix="octelium-harbor-") as temporary:
        directory = pathlib.Path(temporary)
        with helper.native_transport(directory) as environment:
            reconcile(client, environment, desired, directory, args.execute)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, subprocess.SubprocessError, OSError):
        raise SystemExit("Harbor transport reconciliation failed; private output withheld") from None
