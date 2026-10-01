#!/usr/bin/env python3
"""Inspect or reconcile only Langfuse's human-authenticated Octelium Service."""
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
NAME = "langfuse.default"
API_ERROR = re.compile(r"Could not (?:list|get|create|update|apply|authenticate)|gRPC error|\brpc error\b")
NOT_FOUND = re.compile(r"^gRPC error NotFound:|\bcode = NotFound\b", re.MULTILINE)


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
    run("git", "-C", str(ROOT), "cat-file", "-e", "HEAD:scripts/octelium-langfuse-reconcile.py")


def valid_contract(service):
    try:
        spec = service.get("spec", {})
        config = spec.get("config", {})
        header = config.get("http", {}).get("header", {})
        return (service.get("kind") == "Service"
                and service.get("metadata", {}).get("name") in ("langfuse", NAME)
                and spec.get("isPublic") is True and spec.get("isAnonymous", False) is False
                and spec.get("mode") == "WEB" and spec.get("port") == 80
                and spec.get("authorization", {}).get("policies") == ["homelab-human-web-access"]
                and config.get("upstream", {}).get("url") ==
                "https://istio-ingressgateway.istio-system.svc.cluster.local:443"
                and config.get("tls", {}).get("insecureSkipVerify") is True
                and header.get("forwardedMode") == "TRANSPARENT"
                and header.get("host", {}).get("value") == "langfuse.stinkyboi.com"
                and header.get("addRequestHeaders") == [
                    {"key": "X-Forwarded-Host", "value": "langfuse.stinkyboi.com"},
                    {"key": "X-Forwarded-Port", "value": "443"},
                    {"key": "X-Forwarded-Proto", "value": "https"},
                ])
    except (AttributeError, TypeError):
        return False


def declared_service():
    result = run("yq", "ea", "-o=json", "-I=0",
                 'select(.kind == "Service" and .metadata.name == "langfuse")',
                 str(ROOT / "docs/examples/octelium/homelab-services.yaml"))
    desired = json.loads(result.stdout)
    if not valid_contract(desired):
        raise RuntimeError("Langfuse must retain its reviewed human-access and routing contract")
    return {**desired, "metadata": {**desired["metadata"], "name": NAME}}


def reconcile(client, environment, desired, directory, execute):
    def current():
        try:
            result = run(*client, "get", "service", NAME, "-o", "json", env=environment)
        except subprocess.CalledProcessError as error:
            if NOT_FOUND.search((error.stdout or "") + (error.stderr or "")):
                return None
            raise RuntimeError("Native read failed; absence is not established") from None
        output = result.stdout + result.stderr
        if API_ERROR.search(output):
            if NOT_FOUND.search(output):
                return None
            raise RuntimeError("Native read reported a failure")
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or value.get("metadata", {}).get("name") != NAME:
            raise RuntimeError("Unexpected Service identity")
        return value

    before = current()
    print("Langfuse Service present:", before is not None)
    print("Langfuse human-access and routing contract matches:", before is not None and valid_contract(before))
    if not execute:
        print("Read-only check; no catalog resources changed")
        return
    if not valid_contract(desired) or desired["metadata"]["name"] != NAME:
        raise RuntimeError("Refusing an unexpected Service contract")
    manifest = directory / "langfuse.json"
    manifest.write_text(json.dumps(desired))
    manifest.chmod(0o600)
    for _ in range(2):
        result = run(*client, "apply", "--include", "Service", str(manifest), env=environment)
        if API_ERROR.search(result.stdout + result.stderr):
            raise RuntimeError("Native apply reported a failure")
    if "No applied changes in Cluster Core resources" not in result.stdout:
        raise RuntimeError("Repeated apply did not converge")
    after = current()
    if after is None or not valid_contract(after):
        raise RuntimeError("Langfuse human-access and routing contract did not converge")
    print("Verified Langfuse convergence and non-anonymous human access")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--homedir", help="Existing private Octelium operator login directory")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda signum, _: sys.exit(128 + signum))
    if args.execute:
        verify_reviewed_main(args.expected_sha)
    # Reuse the reviewed carrier only after the clean/exact-main execution guard.
    source = importlib.util.spec_from_file_location("native_transport", ROOT / "scripts/octelium-nofx-reconcile.py")
    helper = importlib.util.module_from_spec(source)
    source.loader.exec_module(helper)
    desired = declared_service()
    client = [helper.verified_client(), "--domain", "stinkyboi.com"]
    if args.homedir:
        client += ["--homedir", str(pathlib.Path(args.homedir).resolve())]
    with tempfile.TemporaryDirectory(prefix="octelium-langfuse-") as temporary:
        directory = pathlib.Path(temporary)
        with helper.native_transport(directory) as environment:
            reconcile(client, environment, desired, directory, args.execute)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, subprocess.SubprocessError, OSError, IndexError):
        raise SystemExit("Langfuse catalog reconciliation failed; private output withheld") from None
