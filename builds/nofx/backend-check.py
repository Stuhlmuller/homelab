#!/usr/bin/env python3
"""Verify built backend startup and SQLite persistence with disposable data."""

import base64
import ipaddress
import json
import secrets
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

BUSYBOX = "cgr.dev/chainguard/busybox@sha256:f7d9063f22547e726221275158930e5033be3c6d8340c6867afb7d0d779fad8d"


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def main():
    name = "nofx-backend-" + uuid4().hex[:12]
    network, volume = name + "-network", name + "-data"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    created_network = created_volume = False
    with tempfile.TemporaryDirectory(prefix="nofx-backend-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        key = run("openssl", "genrsa", "-traditional", "2048")
        config = root / "fixture.env"
        config.write_text("\n".join([
            "DB_TYPE=sqlite", "DB_PATH=/app/data/data.db", "API_SERVER_PORT=8080",
            "EXPERIENCE_IMPROVEMENT=false", "TRANSPORT_ENCRYPTION=true",
            "JWT_SECRET=" + secrets.token_hex(32),
            "DATA_ENCRYPTION_KEY=" + base64.b64encode(secrets.token_bytes(32)).decode(),
            "RSA_PRIVATE_KEY=" + json.dumps(key),
        ]) + "\n")
        config.chmod(0o444)
        try:
            run("docker", "network", "create", "--internal", network)
            created_network = True
            run("docker", "volume", "create", volume)
            created_volume = True
            run("docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
                "--cap-add", "CHOWN", "--cap-add", "FOWNER", "--user", "0:0",
                "--volume", volume + ":/fixture", "--entrypoint", "/bin/sh", BUSYBOX,
                "-ec", "chown 10000:10000 /fixture; chmod 700 /fixture")
            run("docker", "run", "--detach", "--name", name, "--network", network,
                "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--user", "10000:10000", "--memory", "512m", "--cpus", "1",
                "--volume", volume + ":/app/data", "--volume", f"{config}:/app/data/.env:ro",
                "--tmpfs", "/tmp:rw,nosuid,nodev,size=32m,uid=10000,gid=10000",
                "homelab-nofx-backend:build")
            installation_id = None
            for cycle in range(2):
                inspect = json.loads(run("docker", "inspect", name))[0]
                address = inspect["NetworkSettings"]["Networks"][network]["IPAddress"]
                assert ipaddress.IPv4Address(address).is_private
                for attempt in range(60):
                    try:
                        with opener.open("http://" + address + ":8080/api/health", timeout=2) as response:
                            assert response.status == 200 and json.load(response)
                        break
                    except OSError:
                        if attempt == 59:
                            raise
                        time.sleep(1)
                run("docker", "stop", "--time", "20", name)
                assert run("docker", "inspect", "--format", "{{.State.ExitCode}}", name) == "0"
                snapshot = root / (f"database-{cycle}.db")
                run("docker", "cp", name + ":/app/data/data.db", str(snapshot))
                with sqlite3.connect(snapshot) as database:
                    assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                    value = database.execute("SELECT value FROM system_config WHERE key='installation_id'").fetchone()
                    assert value and value[0]
                    if installation_id is None:
                        installation_id = value[0]
                    else:
                        assert value[0] == installation_id, "Restart lost retained SQLite state"
                if cycle == 0:
                    run("docker", "start", name)
            print("Backend UID 10000/read-only root: crypto startup, HTTP health, SQLite integrity and retained restart state passed")
        except Exception:
            logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True, timeout=10)
            print(logs.stdout + logs.stderr)
            raise
        finally:
            subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=30, check=False)
            if created_volume:
                subprocess.run(["docker", "volume", "rm", volume], capture_output=True, timeout=30, check=False)
            if created_network:
                subprocess.run(["docker", "network", "rm", network], capture_output=True, timeout=30, check=False)


if __name__ == "__main__":
    main()
