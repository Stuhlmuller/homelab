#!/usr/bin/env python3
"""Check public gRPC-Web and TLS gRPC carried over a Cloudflare TCP tunnel."""

import argparse
import socket
import subprocess
import tempfile
import time
from pathlib import Path


def has_status_16(data):
    return any(line.lower() == b"grpc-status: 16" for line in data.splitlines())


def probe(api, directory, *, port=None):
    headers = directory / "headers"
    body = directory / "body"
    protocol = "application/grpc" if port else "application/grpc-web+proto"
    command = [
        "curl", "--silent", "--show-error", "--http2", "--max-time", "15",
        "--header", f"content-type: {protocol}",
        "--header", "TE: trailers",  # codespell:ignore te
        "--header", "x-grpc-web: 1", "--data-binary", "",
        "--dump-header", str(headers), "--output", str(body),
        "--write-out", "%{http_code} %{http_version}",
    ]
    if port:
        command += ["--connect-to", f"{api}:443:127.0.0.1:{port}"]
    else:
        answer = subprocess.run(
            ["dig", "+short", "@1.1.1.1", api, "A"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        addresses = []
        for value in answer.stdout.splitlines():
            try:
                socket.inet_pton(socket.AF_INET, value)
                addresses.append(value)
            except OSError:
                pass
        if not addresses:
            return False
        command += ["--resolve", f"{api}:443:{addresses[0]}"]
    command += [f"https://{api}/octelium.api.main.user.v1.MainService/GetStatus"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    if result.returncode or result.stdout.strip() != "200 2":
        return False
    header_text = headers.read_bytes().lower()
    if f"content-type: {protocol}".encode() not in header_text:
        return False
    if port:
        return has_status_16(header_text)
    # gRPC-Web transports trailers as a length-prefixed body frame.
    payload = body.read_bytes()
    while len(payload) >= 5:
        flag, length = payload[0], int.from_bytes(payload[1:5], "big")
        if len(payload) < 5 + length:
            return False
        frame, payload = payload[5:5 + length], payload[5 + length:]
        if flag == 128:
            return not payload and has_status_16(frame)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default="stinkyboi.com")
    args = parser.parse_args()
    api = f"octelium-api.{args.domain}"
    with tempfile.TemporaryDirectory(prefix="octelium-tunnel-check-") as temporary:
        directory = Path(temporary)
        if not probe(api, directory):
            raise SystemExit("FAIL: public browser gRPC-Web did not return unauthenticated status 16")
        print("PASS: public browser gRPC-Web returned status 16", flush=True)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        with (directory / "carrier.log").open("wb") as log:
            carrier = subprocess.Popen([
                "cloudflared", "access", "tcp", "--hostname",
                f"octelium-transport.{args.domain}", "--url", f"127.0.0.1:{port}",
            ], stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline and carrier.poll() is None:
                    if probe(api, directory, port=port):
                        print("PASS: TCP tunnel preserved verified TLS, HTTP/2, and gRPC status 16")
                        return
                    time.sleep(1)
                raise SystemExit("FAIL: native API over the TCP tunnel did not return status 16")
            finally:
                carrier.terminate()
                try:
                    carrier.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    carrier.kill()
                    carrier.wait()


if __name__ == "__main__":
    main()
