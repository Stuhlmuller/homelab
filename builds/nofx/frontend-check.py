#!/usr/bin/env python3
"""Exercise the built frontend against an isolated synthetic API backend."""

import json
import re
import subprocess
import time
import urllib.request
from uuid import uuid4

PYTHON = "cgr.dev/chainguard/python@sha256:197cf542e9f4dc373864faecd4fd1a4f642622e654e9196881ca852e8fdf26bd"
BACKEND = """
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0'))).decode()
        data = json.dumps({'path':self.path,'method':self.command,'body':body,
                           'authorization':self.headers.get('Authorization'),
                           'cookie':self.headers.get('Cookie'),'host':self.headers.get('Host')}).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    do_POST = do_GET
HTTPServer(('0.0.0.0',8080),Handler).serve_forever()
"""


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def main():
    prefix = "nofx-http-" + uuid4().hex[:12]
    backend, frontend = prefix + "-backend", prefix + "-frontend"
    created_network = False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        run("docker", "network", "create", "--internal", prefix)
        created_network = True
        common = ["--detach", "--network", prefix, "--read-only", "--cap-drop", "ALL",
                  "--security-opt", "no-new-privileges", "--memory", "256m", "--cpus", "1"]
        run("docker", "run", *common, "--name", backend, "--network-alias", "nofx",
            "--user", "65532:65532", "--entrypoint", "/usr/bin/python3", PYTHON, "-I", "-B", "-c", BACKEND)
        run("docker", "run", *common, "--name", frontend, "--user", "10000:10000",
            "--sysctl", "net.ipv4.ip_unprivileged_port_start=0", "--publish", "127.0.0.1::80",
            "--tmpfs", "/var/cache/nginx:rw,nosuid,nodev,size=32m,uid=10000,gid=10000",
            "--tmpfs", "/var/run:rw,nosuid,nodev,size=16m,uid=10000,gid=10000",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m,uid=10000,gid=10000",
            "homelab-nofx-frontend:build")
        address = run("docker", "port", frontend, "80/tcp")
        assert re.fullmatch(r"127\.0\.0\.1:[0-9]+", address), address
        base = "http://" + address
        for attempt in range(30):
            try:
                with opener.open(base + "/health", timeout=2) as response:
                    assert response.status == 200 and response.read() == b"OK\n"
                break
            except OSError:
                if attempt == 29:
                    raise
                time.sleep(1)
        with opener.open(base + "/", timeout=5) as response:
            index = response.read()
            assert b"<html" in index.lower()
        with opener.open(base + "/backtest/synthetic-route", timeout=5) as response:
            assert response.read() == index, "SPA fallback changed"
        asset = re.search(rb'"(/assets/[^" ]+\.(?:js|css))"', index)
        assert asset, "Built frontend contains no static asset"
        with opener.open(base + asset[1].decode(), timeout=5) as response:
            assert response.status == 200 and response.read()
            assert "public, immutable" in response.headers.get_all("Cache-Control", [])
        for method, body in (("GET", None), ("POST", b'{"fixture":42}')):
            request = urllib.request.Request(base + "/api/synthetic?keep=query", data=body, method=method,
                                             headers={"Authorization": "Bearer fixture-only", "Cookie": "fixture=session"})
            with opener.open(request, timeout=5) as response:
                value = json.load(response)
            assert value == {"path": "/api/synthetic?keep=query", "method": method,
                             "body": body.decode() if body else "", "authorization": "Bearer fixture-only",
                             "cookie": "fixture=session", "host": "127.0.0.1"}, value
        print("Frontend UID 10000, health, static assets/cache, SPA and authenticated GET/POST proxy passed")
    except Exception:
        for name in (backend, frontend):
            logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True, timeout=10)
            print(logs.stdout + logs.stderr)
        raise
    finally:
        for name in (frontend, backend):
            subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=30, check=False)
        if created_network:
            subprocess.run(["docker", "network", "rm", prefix], capture_output=True, timeout=30, check=False)


if __name__ == "__main__":
    main()
