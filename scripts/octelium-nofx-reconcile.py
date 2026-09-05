#!/usr/bin/env python3
"""Inspect or reconcile the single repository-owned NOFX Service over Tunnel."""
import argparse
import contextlib
import importlib.util
import json
import os
import pathlib
import re
import select
import signal
import shutil
import socket
import socketserver
import subprocess
import tempfile
import threading
import time

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


def declared_service():
    service = json.loads(run("yq", "ea", "-o=json", "-I=0",
        'select(.kind == "Service" and .metadata.name == "nofx")', str(ROOT / CATALOG)).stdout)
    if (service.get("kind") != "Service" or service.get("metadata", {}).get("name") != "nofx"
            or service.get("spec", {}).get("isAnonymous") is not False
            or service["spec"].get("authorization", {}).get("policies") != ["homelab-human-web-access"]):
        raise RuntimeError("NOFX catalog must retain the reviewed non-anonymous human-access contract")
    return service


def verify_reviewed_main(expected):
    if not expected or not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise RuntimeError("Execution requires --expected-sha with the full reviewed main commit")
    head = run("git", "-C", str(ROOT), "rev-parse", "HEAD").stdout.strip()
    remote = run("git", "ls-remote", "https://github.com/Stuhlmuller/homelab.git", "refs/heads/main").stdout.split()[0]
    if head != expected or remote != expected:
        raise RuntimeError("Checkout and remote main must match the reviewed execution commit")
    run("git", "-C", str(ROOT), "cat-file", "-e", "HEAD:scripts/octelium-nofx-reconcile.py")
    run("git", "-C", str(ROOT), "diff", "--quiet", "HEAD", "--", CATALOG,
        "scripts/octelium-nofx-reconcile.py", "scripts/octelium-tunnel-check.py")


@contextlib.contextmanager
def native_transport(directory):
    spec = importlib.util.spec_from_file_location("tunnel_probe", ROOT / "scripts/octelium-tunnel-check.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(15)
            request = self.rfile.readline(4096).strip()
            if request != f"CONNECT {API}:443 HTTP/1.1".encode():
                self.wfile.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                return
            total = 0
            while True:
                line = self.rfile.readline(4096)
                total += len(line)
                if total > 16384 or not line:
                    return
                if line == b"\r\n":
                    break
            with socket.create_connection(("127.0.0.1", port), timeout=15) as upstream:
                self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self.wfile.flush()
                while True:
                    ready, _, _ = select.select([self.connection, upstream], [], [], 60)
                    if not ready:
                        return
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        (upstream if source is self.connection else self.connection).sendall(data)

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True

        def handle_error(self, _request, _client_address):
            # The bounded native command reports failure without private proxy diagnostics.
            return

    with (directory / "carrier.log").open("wb") as log:
        carrier = subprocess.Popen(["cloudflared", "access", "tcp", "--hostname",
            "octelium-transport.stinkyboi.com", "--url", f"127.0.0.1:{port}"], stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 45
            while carrier.poll() is None and time.monotonic() < deadline:
                if probe.probe(API, directory, port=port):
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Native Tunnel TLS/HTTP2 probe failed")
            with Server(("127.0.0.1", 0), Handler) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    # Internal, dynamically allocated client transport, not desired-state inputs.
                    environment = dict(os.environ)
                    proxy = f"http://127.0.0.1:{server.server_address[1]}"
                    for key in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
                        environment[key] = proxy
                    environment["NO_PROXY"] = environment["no_proxy"] = ""
                    yield environment
                finally:
                    server.shutdown()
                    thread.join(timeout=2)
        finally:
            carrier.terminate()
            try:
                carrier.wait(timeout=5)
            except subprocess.TimeoutExpired:
                carrier.kill()
                carrier.wait()


def reconcile(client, environment, desired, directory, execute):
    def current():
        value = json.loads(run(*client, "get", "service", "nofx.default", "-o", "json", env=environment).stdout)
        if value.get("metadata", {}).get("name") != "nofx.default":
            raise RuntimeError("Unexpected Service identity")
        return value

    before = current()
    print("NOFX anonymous access:", before["spec"].get("isAnonymous", False))
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
    if after["spec"].get("isAnonymous", False) is not False:
        raise RuntimeError("NOFX still permits anonymous access")
    if after["spec"].get("authorization", {}).get("policies") != ["homelab-human-web-access"]:
        raise RuntimeError("NOFX human-access policy was not restored")
    print("Verified NOFX catalog convergence and disabled anonymous access")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--homedir", help="Private existing operator login directory; defaults to the native client default")
    parser.add_argument("--execute", action="store_true", help="Apply only the declared NOFX Service")
    parser.add_argument("--expected-sha", help="Exact reviewed main commit required for execution")
    args = parser.parse_args()
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    desired = declared_service()
    if args.execute:
        verify_reviewed_main(args.expected_sha)
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
