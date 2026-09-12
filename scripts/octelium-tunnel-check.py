#!/usr/bin/env python3
"""Check public gRPC-Web and TLS gRPC carried over a Cloudflare TCP tunnel."""

import argparse
import re
import socket
import subprocess
import tempfile
import time
from pathlib import Path


def fields(lines):
    """Parse field names exactly and retain duplicates for validation."""
    result = {}
    for line in lines:
        name, colon, value = line.partition(b":")
        if not colon or not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
            return None
        result.setdefault(name.lower(), []).append(value.strip(b" \t"))
    return result


def final_response(data):
    """Separate curl's final response headers from its following HTTP trailers."""
    status, headers, trailers = None, None, {}
    for block in re.split(rb"\r?\n\r?\n", data):
        lines = block.splitlines()
        if not lines:
            continue
        match = re.fullmatch(rb"HTTP/(1\.[01]|2|3) ([1-5][0-9]{2})(?:[ \t].*)?", lines[0])
        if match:
            status, headers, trailers = match.groups(), fields(lines[1:]), {}
            if headers is None:
                return None
        else:
            following = fields(lines)
            if headers is None or following is None:
                return None
            for name, values in following.items():
                trailers.setdefault(name, []).extend(values)
    return (headers, trailers) if status == (b"2", b"200") else None


def has_status_16(headers):
    return headers is not None and headers.get(b"grpc-status") == [b"16"]


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
                # dig can include CNAME answers; only IPv4 addresses can pin curl.
                pass
        if not addresses:
            return False
        command += ["--resolve", f"{api}:443:{addresses[0]}"]
    command += [f"https://{api}/octelium.api.main.user.v1.MainService/GetStatus"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    if result.returncode or result.stdout.strip() != "200 2":
        return False
    response = final_response(headers.read_bytes())
    if response is None:
        return False
    response_headers, http_trailers = response
    content_types = response_headers.get(b"content-type", [])
    accepted_types = {protocol.encode(), b"application/grpc+proto"} if port else {protocol.encode()}
    if (len(content_types) != 1 or b"content-type" in http_trailers
            or content_types[0].split(b";", 1)[0].strip(b" \t").lower() not in accepted_types):
        return False
    payload = body.read_bytes()
    if port:
        if b"grpc-status" in response_headers:
            return not payload and b"grpc-status" not in http_trailers and has_status_16(response_headers)
        return has_status_16(http_trailers)
    if b"grpc-status" in http_trailers:
        return False
    # gRPC-Web permits a trailers-only response in the headers with no body.
    if not payload:
        return has_status_16(response_headers)
    if b"grpc-status" in response_headers:
        return False
    # Responses with a body must finish with a length-prefixed trailer frame.
    while len(payload) >= 5:
        flag, length = payload[0], int.from_bytes(payload[1:5], "big")
        if len(payload) < 5 + length:
            return False
        frame, payload = payload[5:5 + length], payload[5 + length:]
        if flag == 128:
            return not payload and has_status_16(fields(frame.splitlines()))
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
