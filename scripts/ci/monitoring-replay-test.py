#!/usr/bin/env python3
"""Real pinned binaries, synthetic state only; no production access or receivers."""

import argparse
import datetime
import importlib.util
import json
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "checkpoint", Path(__file__).resolve().parents[1] / "monitoring-checkpoint.py"
)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(url, data=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=2) as response:
        return response.read()


@contextmanager
def server(command, ready):
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(command, stdout=log, stderr=log)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("synthetic application exited before readiness")
                try:
                    request(ready)
                    break
                except (OSError, TimeoutError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("synthetic readiness timeout")
            yield
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise RuntimeError("synthetic application did not shut down cleanly")
        assert process.returncode == 0, "unclean synthetic shutdown"


class Metrics(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(b"# TYPE recovery_fixture gauge\nrecovery_fixture 42\n")

    def log_message(self, *args):
        pass


def copy_state(root, source, app):
    # Tests use a no-op fence ONLY because these are owned, stopped subprocesses
    # on disposable synthetic files. Production CLI cannot select this gate.
    plan = {
        "workload": app,
        "migration_id": "synthetic",
        "source_pvc_uid": "old",
        "source_pv": "old-pv",
        "target_pvc_uid": "new",
        "target_pv": "new-pv",
        "application_image_digest": "synthetic-binary",
    }
    checkpoint = root / (app + "-checkpoint")
    checksum = M.checkpoint(plan, source, checkpoint, lambda: None)
    # Mocked external proof tests the copy path; this is not an independent backup.
    proof = {
        "manifest_sha256": checksum,
        "isolated_application_restore_passed": True,
        "independent_backup_retrieved": True,
        "application_image_digest": "synthetic-binary",
    }
    destination = root / (app + "-restored")
    M.restore(plan, checkpoint, destination, proof, lambda: None)
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prometheus", required=True, type=Path)
    parser.add_argument("--alertmanager", required=True, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        metrics = ThreadingHTTPServer(("127.0.0.1", 0), Metrics)
        worker = threading.Thread(target=metrics.serve_forever)
        worker.start()
        try:
            prometheus_port = port()
            base = f"http://127.0.0.1:{prometheus_port}"
            config = root / "prometheus.yaml"
            config.write_text(
                "global:\n  scrape_interval: 1s\nscrape_configs:\n"
                "  - job_name: synthetic\n    static_configs:\n"
                f"      - targets: ['127.0.0.1:{metrics.server_port}']\n"
            )
            source = root / "prometheus"
            source.mkdir()

            def prom_command(data):
                return [
                    str(args.prometheus.resolve()),
                    f"--config.file={config}",
                    f"--storage.tsdb.path={data}",
                    f"--web.listen-address=127.0.0.1:{prometheus_port}",
                ]

            with server(prom_command(source), base + "/-/ready"):
                for _ in range(200):
                    result = json.loads(
                        request(base + "/api/v1/query?query=recovery_fixture")
                    )
                    if result["data"]["result"]:
                        break
                    time.sleep(0.1)
                else:
                    raise RuntimeError(
                        "no synthetic ingestion: "
                        + request(base + "/api/v1/targets").decode()
                    )
                query_time = time.time()
                assert result["data"]["result"][0]["value"][1] == "42"
            assert any((source / "wal").iterdir())
            restored = copy_state(root, source, "prometheus")
            config.write_text("global:\n  scrape_interval: 1s\nscrape_configs: []\n")
            with server(prom_command(restored), base + "/-/ready"):
                query = urllib.parse.urlencode(
                    {"query": "recovery_fixture", "time": query_time}
                )
                result = json.loads(request(base + "/api/v1/query?" + query))
                assert result["data"]["result"][0]["value"][1] == "42"
        finally:
            metrics.shutdown()
            metrics.server_close()
            worker.join()

        alert_port = port()
        base = f"http://127.0.0.1:{alert_port}"
        config = root / "alertmanager.yaml"
        config.write_text(
            "route:\n  receiver: null-receiver\nreceivers:\n  - name: null-receiver\n"
        )
        source = root / "alertmanager"
        source.mkdir()

        def alert_command(data):
            return [
                str(args.alertmanager.resolve()),
                f"--config.file={config}",
                f"--storage.path={data}",
                f"--web.listen-address=127.0.0.1:{alert_port}",
                "--cluster.listen-address=",
            ]

        now = datetime.datetime.now(datetime.timezone.utc)
        with server(alert_command(source), base + "/-/ready"):
            response = json.loads(
                request(
                    base + "/api/v2/silences",
                    {
                        "matchers": [
                            {
                                "name": "alertname",
                                "value": "SyntheticOnly",
                                "isRegex": False,
                            }
                        ],
                        "startsAt": now.isoformat(),
                        "endsAt": (now + datetime.timedelta(hours=1)).isoformat(),
                        "createdBy": "synthetic-test",
                        "comment": "synthetic restore fixture",
                    },
                )
            )
            silence_id = response["silenceID"]
        restored = copy_state(root, source, "alertmanager")
        with server(alert_command(restored), base + "/-/ready"):
            silences = json.loads(request(base + "/api/v2/silences"))
            assert any(
                s["id"] == silence_id and s["status"]["state"] == "active"
                for s in silences
            )
    print(
        "Synthetic Prometheus ingestion/WAL/history and Alertmanager silence replay passed."
    )


if __name__ == "__main__":
    main()
