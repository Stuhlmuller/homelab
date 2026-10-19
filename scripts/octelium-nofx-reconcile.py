#!/usr/bin/env python3
"""Inspect or reconcile the single repository-owned NOFX Service over the verified Tailscale mesh."""
import sys

# sys is built in. Reject unsafe module search paths before any other imports.
if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
import contextlib
import ipaddress
import json
import os
import pathlib
import re
import runpy
import signal
import shutil
import socket
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOG = "docs/examples/octelium/homelab-services.yaml"
API = "octelium-api.stinkyboi.com"


def run(*command, **kwargs):
    return subprocess.run(command, capture_output=True, text=True, timeout=45, check=True, **kwargs)


def verified_client():
    executable = shutil.which("octeliumctl")
    if not executable:
        raise RuntimeError("Install the pinned CLI with scripts/install-octeliumctl.sh")
    version = run(executable, "version").stdout
    expected = {"releaseVersion": "v0.35.0", "gitCommit": "5e4eb3e36911ba4f66f5f43df2cc4b264211c4ce"}
    fields = dict(re.findall(r"^([A-Za-z]+):\s*(\S+)\s*$", version, re.MULTILINE))
    if any(fields.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Octelium CLI must match the pinned release and source commit")
    return executable


def authorization_mode(service):
    return service.get("spec", {}).get("config", {}).get("http", {}).get("header", {}).get("authorizationMode")


def declared_service():
    service = json.loads(run("yq", "ea", "-o=json", "-I=0",
        'select(.kind == "Service" and .metadata.name == "nofx")', str(ROOT / CATALOG)).stdout)
    if (service.get("kind") != "Service" or service.get("metadata", {}).get("name") != "nofx"
            or service.get("spec", {}).get("isAnonymous") is not False
            or service["spec"].get("authorization", {}).get("policies") != ["homelab-human-web-access"]
            or authorization_mode(service) != "PASS"):
        raise RuntimeError("NOFX catalog must retain the reviewed non-anonymous human-access contract")
    return service


def verify_reviewed_main(expected):
    if not expected or not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise RuntimeError("Execution requires --expected-sha with the full reviewed main commit")
    if run("git", "-C", str(ROOT), "status", "--porcelain=v1",
           "--untracked-files=all", "--ignore-submodules=none").stdout:
        raise RuntimeError("Execution requires a clean checkout, including untracked files")
    head = run("git", "-C", str(ROOT), "rev-parse", "HEAD").stdout.strip()
    remote = run("git", "ls-remote", "https://github.com/Stuhlmuller/homelab.git", "refs/heads/main").stdout.split()[0]
    if head != expected or remote != expected:
        raise RuntimeError("Checkout and remote main must match the reviewed execution commit")
    run("git", "-C", str(ROOT), "cat-file", "-e", "HEAD:scripts/octelium-nofx-reconcile.py")


def mesh_environment():
    if (os.environ.get("OCTELIUM_INSECURE_TLS") == "true"
            or os.environ.get("OCTELIUM_AUTH_PROXY_SOCKET")):
        raise RuntimeError("Native overrides must not bypass TLS or authentication")
    app = pathlib.Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
    executable = str(app) if app.is_file() else shutil.which("tailscale")
    if not executable:
        raise RuntimeError("An authenticated Tailscale client is required")
    status = json.loads(run(executable, "status", "--json").stdout)
    if (status.get("BackendState") != "Running" or not status.get("Self", {}).get("Online")
            or status.get("CurrentTailnet", {}).get("MagicDNSSuffix") != "tail67beb.ts.net"):
        raise RuntimeError("The current Tailscale profile must be online in the declared tailnet")
    peers = [peer for peer in status.get("Peer", {}).values()
             if peer.get("DNSName", "").rstrip(".") == "homelab-ingress.tail67beb.ts.net" and peer.get("Online")]
    if len(peers) != 1:
        raise RuntimeError("The declared homelab-ingress peer must be uniquely online")
    allowed = {ipaddress.ip_address(value) for value in peers[0].get("TailscaleIPs", [])}
    networks = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))
    resolved = {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(API, 443, type=socket.SOCK_STREAM)}
    if (not resolved or not resolved <= allowed
            or any(not any(address in network for network in networks) for address in resolved)):
        raise RuntimeError("Canonical Octelium API must resolve only to the verified mesh ingress peer")
    environment = {key: value for key, value in os.environ.items()
                   if key.lower() not in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")}
    validate = runpy.run_path(str(ROOT / "scripts/octelium-api-response.py"))["unauthenticated"]
    with tempfile.TemporaryDirectory(prefix="homelab-api-probe-") as temporary:
        body = pathlib.Path(temporary) / "body"
        for protocol in ("application/grpc", "application/grpc-web+proto"):
            result = run("curl", "--disable", "--silent", "--show-error", "--http2", "--max-time", "10",
                         "--noproxy", "*", "--proto", "=https", "--header", f"content-type: {protocol}",
                         "--header", "x-grpc-web: 1", "--header", "TE: trailers",  # codespell:ignore te
                         "--data-binary", "", "--dump-header", "-", "--output", str(body),
                         f"https://{API}/octelium.api.main.user.v1.MainService/GetStatus", env=environment)
            if not validate(result.stdout.encode(), body.read_bytes(), native=protocol == "application/grpc"):
                raise RuntimeError("Native mesh TLS/HTTP2 authentication probe failed")
    return environment


@contextlib.contextmanager
def native_transport(_directory):
    # Keep the shared caller interface; native clients now connect directly over TLS.
    yield mesh_environment()


def reconcile(client, environment, desired, directory, execute):
    def current():
        try:
            result = run(*client, "get", "service", "nofx.default", "-o", "json", env=environment)
        except subprocess.CalledProcessError as error:
            if (re.search(r"^gRPC error NotFound:", error.stdout or "", re.MULTILINE)
                    or re.search(r"\bcode = NotFound\b", error.stderr or "")):
                return None
            raise RuntimeError("Native inspection failed; absence is not established") from None
        value = json.loads(result.stdout)
        if value.get("metadata", {}).get("name") != "nofx.default":
            raise RuntimeError("Unexpected Service identity")
        return value

    before = current()
    print("NOFX Service present:", before is not None)
    if before is not None:
        print("NOFX anonymous access:", before["spec"].get("isAnonymous", False))
        print("NOFX authorization passthrough:", authorization_mode(before) == "PASS")
    if not execute:
        print("Read-only check; no catalog resources changed")
        return
    manifest = directory / "nofx.json"
    # Make the catalog's default namespace explicit for any operator context.
    desired = {**desired, "metadata": {**desired["metadata"], "name": "nofx.default"}}
    manifest.write_text(json.dumps(desired))
    manifest.chmod(0o600)
    for _ in range(2):
        result = run(*client, "apply", "--include", "Service", str(manifest), env=environment)
        if re.search(r"Could not (list|create|update|apply)|gRPC error", result.stdout + result.stderr):
            raise RuntimeError("Native catalog apply reported a failure")
    if "No applied changes in Cluster Core resources" not in result.stdout:
        raise RuntimeError("Second catalog apply did not prove convergence")
    after = current()
    if after is None:
        raise RuntimeError("NOFX Service remains absent after reconciliation")
    if authorization_mode(after) != "PASS":
        raise RuntimeError("NOFX authorization passthrough was not restored")
    if after["spec"].get("isAnonymous", False) is not False:
        raise RuntimeError("NOFX still permits anonymous access")
    if after["spec"].get("authorization", {}).get("policies") != ["homelab-human-web-access"]:
        raise RuntimeError("NOFX human-access policy was not restored")
    print("Verified NOFX convergence, disabled anonymous access, and authorization passthrough")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--homedir", help="Private existing operator login directory; defaults to the native client default")
    parser.add_argument("--execute", action="store_true", help="Apply only the declared NOFX Service")
    parser.add_argument("--expected-sha", help="Exact reviewed main commit required for execution")
    args = parser.parse_args()
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    if args.execute:
        verify_reviewed_main(args.expected_sha)
    desired = declared_service()
    client = [verified_client(), "--domain", "stinkyboi.com"]
    if args.homedir:
        client += ["--homedir", str(pathlib.Path(args.homedir).resolve())]
    with tempfile.TemporaryDirectory(prefix="octelium-nofx-") as temporary:
        directory = pathlib.Path(temporary)
        with native_transport(directory) as environment:
            reconcile(client, environment, desired, directory, args.execute)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, subprocess.SubprocessError, OSError):
        raise SystemExit("NOFX reconciliation failed; private native-client output withheld") from None
