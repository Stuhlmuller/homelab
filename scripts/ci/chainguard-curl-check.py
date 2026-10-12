"""Run Kiali's declared readiness command in a disposable non-root curl image."""

import http.server
import json
from pathlib import Path
import socketserver
import subprocess
import tempfile
import threading
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
values = json.loads(subprocess.check_output([
    "yq", "-o=json", ".", str(ROOT / "clusters/homelab/apps/kiali/values.yaml")], text=True))
container = values["cr"]["spec"]["deployment"]["additional_pod_init_containers_yaml"][0]
assert container["command"] == ["/usr/bin/curl"]
assert container["image"].startswith("harbor.stinkyboi.com/mirror/cgr.dev/chainguard/curl:latest@sha256:")
security = container["securityContext"]
assert security["runAsUser"] == security["runAsGroup"] == 65532
assert security["runAsNonRoot"] is True and security["readOnlyRootFilesystem"] is True
assert security["allowPrivilegeEscalation"] is False and security["capabilities"]["drop"] == ["ALL"]
url = urlsplit(container["args"][-1])
assert url.scheme == "http" and url.path == "/-/ready"
requests = []


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        requests.append((self.path, self.headers["Host"]))
        assert self.path == url.path and self.headers["Host"] == url.netloc
        self.send_response(503 if len(requests) == 1 else 200)
        self.end_headers()
        self.wfile.write(b"fixture readiness\n")

    def log_message(self, *args):
        pass


with tempfile.TemporaryDirectory(prefix="curl-compat-") as temporary:
    root = Path(temporary)
    root.chmod(0o755)
    with socketserver.UnixStreamServer(str(root / "socket"), Handler) as server:
        (root / "socket").chmod(0o777)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            source = container["image"].removeprefix("harbor.stinkyboi.com/mirror/")
            subprocess.run(["docker", "run", "--rm", "--network", "none", "--read-only",
                            "--memory", "32m", "--cpus", "0.1",
                            "--user", "65532:65532", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                            "--mount", f"type=bind,source={root},target=/fixture,readonly",
                            "--entrypoint", container["command"][0], source,
                            "--unix-socket", "/fixture/socket", *container["args"]], check=True, timeout=30)
            assert len(requests) == 2, "Declared curl retry must recover from readiness failure"
        finally:
            server.shutdown()
            thread.join(timeout=5)
print("Non-root curl readiness: exact HTTP path/Host, transient failure retry and read-only operation passed; service DNS/network acceptance remains separate")
