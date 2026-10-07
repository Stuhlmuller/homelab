#!/usr/bin/env python3
"""Exercise the NAS media route with real nginx and a loopback mock upstream.

Run from the repository with its pinned tools (no cluster access required):
  nix shell --inputs-from . nixpkgs#nginx nixpkgs#yq-go \
    -c python3 -I scripts/ci/dispatcharr-media-route-test.py
"""

from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time


ROOT = Path(__file__).resolve().parents[2]
VALUES = ROOT / "clusters/homelab/apps/dispatcharr/values.yaml"
CHANNEL = "12345678-1234-1234-1234-123456789abc"
STREAM = f"/proxy/ts/stream/{CHANNEL}"
REQUESTS = []


class Upstream(BaseHTTPRequestHandler):
    def do_GET(self):
        result = {"path": self.path, "headers": dict(self.headers)}
        REQUESTS.append(result)
        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_HEAD = do_GET

    def log_message(self, *_args):
        pass


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def request(port, path, method="GET", headers=None):
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def configuration(prefix, route):
    return f"""daemon off;
master_process off;
error_log stderr;
pid {prefix}/nginx.pid;
events {{ worker_connections 64; }}
http {{
    access_log off;
    client_body_temp_path {prefix}/client-body;
    proxy_temp_path {prefix}/proxy;
    fastcgi_temp_path {prefix}/fastcgi;
    uwsgi_temp_path {prefix}/uwsgi;
    scgi_temp_path {prefix}/scgi;
{route}
}}
"""


@contextmanager
def nginx(route, upstream_port, allow_loopback):
    # Change only test transport/identity; all routes, queries and headers stay real.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    fixture = route.replace("listen 9192;", f"listen 127.0.0.1:{port};")
    fixture = fixture.replace("http://127.0.0.1:9191", f"http://127.0.0.1:{upstream_port}")
    if allow_loopback:
        fixture = fixture.replace("allow 10.1.0.2;", "allow 127.0.0.1;")
    with tempfile.TemporaryDirectory(prefix="dispatcharr-media-test-") as temporary:
        prefix = Path(temporary)
        config = prefix / "nginx.conf"
        config.write_text(configuration(prefix, fixture))
        with (prefix / "nginx.log").open("w+") as log:
            process = subprocess.Popen(
                ["nginx", "-p", str(prefix), "-c", str(config), "-e", "stderr"],
                stdout=log, stderr=log,
            )
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        log.seek(0)
                        raise AssertionError(f"nginx failed: {log.read()}")
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                            break
                    except OSError:
                        time.sleep(0.05)
                else:
                    raise AssertionError("nginx listener did not start")
                yield port
            finally:
                process.terminate()
                process.wait(timeout=5)


def main():
    for command in ("nginx", "yq"):
        require(shutil.which(command), f"{command} missing; use the documented Nix command")
    values = json.loads(subprocess.check_output(["yq", "-o=json", ".", str(VALUES)], text=True))
    configmap = values["configMaps"]["media-route"]
    route = configmap["data"]["dispatcharr-media.conf"]
    require(configmap["includeInChecksum"] and
            configmap["includeChecksumInControllers"] == ["dispatcharr"], "missing rollout checksum")
    require(values["controllers"]["dispatcharr"]["pod"]["nodeSelector"] ==
            {"kubernetes.io/hostname": "acer"}, "NodePort endpoint must stay on acer")
    service = values["service"]["media"]
    require(values["service"]["app"].get("forceRename") == "dispatcharr" and
            values["service"]["app"]["ports"]["http"]["port"] == 9191,
            "existing administrative Service must remain dispatcharr:9191")
    require(service["controller"] == "dispatcharr" and service["type"] == "NodePort" and
            service["externalTrafficPolicy"] == "Local", "NAS source IP must reach nginx unchanged")
    require(service["ports"]["http"] == {"port": 9192, "targetPort": 9192, "nodePort": 31991},
            "unexpected media ports")
    mounts = values["persistence"]["media-route"]
    require(mounts["type"] == "configMap" and mounts["identifier"] == "media-route" and
            mounts["advancedMounts"] == {"dispatcharr": {"app": [{
                "path": "/etc/nginx/conf.d/dispatcharr-media.conf",
                "subPath": "dispatcharr-media.conf", "readOnly": True,
            }]}}, "media config must mount only in the web container")
    require(route.count("listen 9192;") == 1 and route.count("allow 10.1.0.2;") == 1,
            "unexpected production listener or source ACL")

    # Syntax-check the unmodified production fragment, before adapting loopback tests.
    with tempfile.TemporaryDirectory(prefix="dispatcharr-media-syntax-") as temporary:
        prefix = Path(temporary)
        config = prefix / "nginx.conf"
        config.write_text(configuration(prefix, route))
        subprocess.run(["nginx", "-p", str(prefix), "-c", str(config), "-e", "stderr", "-t"], check=True)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    worker = threading.Thread(target=upstream.serve_forever, daemon=True)
    worker.start()
    cases = 0
    try:
        with nginx(route, upstream.server_port, allow_loopback=True) as port:
            allowed = [
                f"/output/{kind}{profile}{slash}{query}"
                for kind in ("m3u", "epg") for profile in ("", "/Sports")
                for slash in ("", "/") for query in ("", "?cachedlogos=false")
            ] + [
                f"/hdhr/{profile}{kind}.json" for profile in ("", "Sports/")
                for kind in ("discover", "lineup", "lineup_status")
            ] + [STREAM, STREAM + "?output_profile=12", "/api/channels/logos/12/cache",
                 "/api/channels/logos/12/cache/"]
            for path in allowed:
                for method in ("GET", "HEAD"):
                    before = len(REQUESTS)
                    status, _ = request(port, path, method)
                    require(status == 200 and len(REQUESTS) == before + 1 and
                            REQUESTS[-1]["path"] == path, f"allowed request failed: {method} {path}")
                    cases += 1

            forged = {
                "Host": "attacker.invalid:1234", "X-Forwarded-Host": "attacker.invalid:1234",
                "X-Forwarded-Port": "1234", "X-Forwarded-Proto": "https",
                "X-Real-IP": "10.1.0.2", "X-Forwarded-For": "10.1.0.2",
                "Forwarded": "for=10.1.0.2;host=attacker.invalid;proto=https",
                "Authorization": "Bearer test-only", "Cookie": "session=test-only",
                "Range": "bytes=0-1023",
            }
            status, body = request(port, STREAM, headers=forged)
            actual = {key.lower(): value for key, value in json.loads(body)["headers"].items()}
            expected = {
                "host": "10.1.0.199:31991", "x-forwarded-host": "10.1.0.199:31991",
                "x-forwarded-port": "31991", "x-forwarded-proto": "http",
                "x-real-ip": "127.0.0.1", "x-forwarded-for": "127.0.0.1", "range": "bytes=0-1023",
            }
            require(status == 200 and all(actual.get(key) == value for key, value in expected.items()) and
                    not any(key in actual for key in ("forwarded", "authorization", "cookie")),
                    f"upstream identity or media headers wrong: {actual}")
            cases += 1

            denied = [
                ("/", 404), ("/admin/", 404), ("/api/accounts/initialize-superuser/", 404),
                ("/api/channels/", 404), ("/api/channels/logos/12/", 404),
                ("/api/channels/logos/cleanup/", 404), ("/hdhr/devices/", 404),
                ("/hdhr/device.xml", 404), ("/hdhr/Other/discover.json", 404),
                ("/output/m3u/Other", 404), ("/output/%2e%2e/api/accounts/", 404),
                (f"/proxy/ts/stop/{CHANNEL}", 404), (f"/proxy/ts/change_stream/{CHANNEL}", 404),
                (f"/proxy/ts/next_stream/{CHANNEL}", 404), ("/proxy/ts/status", 404),
                ("/proxy/ts/stream/not-a-uuid", 404), (STREAM + "/extra", 404),
                ("/output/m3u?direct=true", 400), ("/output/m3u?%64irect=true", 400),
                ("/output/m3u?direct=%74rue", 400), ("/output/m3u?direct=false&direct=true", 400),
                ("/output/m3u?cachedlogos=false&direct=true", 400),
                ("/output/m3u?cachedlogos=false&cachedlogos=false", 400),
                ("/output/m3u?cachedlogos=FALSE", 400), ("/output/epg?output_profile=12", 400),
                ("/hdhr/Sports/lineup.json?direct=true", 400),
                ("/api/channels/logos/12/cache?url=https://attacker.invalid", 400),
                (STREAM + "?output_profile=12&output_profile=13", 400),
                (STREAM + "?output_profile=-1", 400), (STREAM + "?direct=true", 400),
            ]
            for path, expected_status in denied:
                before = len(REQUESTS)
                status, _ = request(port, path)
                require(status == expected_status and len(REQUESTS) == before,
                        f"blocked path reached upstream or wrong status: {path}: {status}")
                cases += 1
            for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
                before = len(REQUESTS)
                status, _ = request(port, "/output/m3u/Sports", method)
                require(status == 405 and len(REQUESTS) == before, f"method not blocked: {method}")
                cases += 1

        # Original NAS ACL: loopback stays denied even when every identity header claims NAS.
        with nginx(route, upstream.server_port, allow_loopback=False) as port:
            for path in ("/output/m3u", "/output/epg/Sports", "/hdhr/Sports/discover.json",
                         STREAM, "/api/channels/logos/12/cache"):
                before = len(REQUESTS)
                status, _ = request(port, path, headers=forged)
                require(status == 403 and len(REQUESTS) == before, f"source ACL bypassed: {path}")
                cases += 1
    finally:
        upstream.shutdown()
        upstream.server_close()
        worker.join(timeout=5)
    print(f"Dispatcharr media route: nginx syntax and {cases} HTTP security checks passed")


if __name__ == "__main__":
    main()
