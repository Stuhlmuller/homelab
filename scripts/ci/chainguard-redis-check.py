#!/usr/bin/env python3
"""Run AFFiNE's declared ephemeral Redis commands with synthetic credentials."""

import json
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "harbor.stinkyboi.com/mirror/cgr.dev/chainguard/redis:latest@sha256:0c5c0510e8a9931fa07a3bba5e8ae03102be674afe5d191b8e2161609278eb29"


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def main():
    documents = json.loads(run("yq", "ea", "-o=json", "-I=0", "[.]",
                              str(ROOT / "clusters/homelab/apps/affine/redis.yaml")))
    statefulset = next(v for v in documents if v.get("kind") == "StatefulSet")
    assert statefulset["spec"]["replicas"] == 0, "Compatibility work must retain suspension"
    pod = statefulset["spec"]["template"]["spec"]
    container = next(v for v in pod["containers"] if v["name"] == "redis")
    assert container["image"] == IMAGE
    assert pod["securityContext"]["runAsUser"] == 65534
    assert container["securityContext"]["readOnlyRootFilesystem"]
    command = container["command"] + container["args"]
    assert command[:2] == ["/bin/sh", "-ec"]
    for password in ("", "REPLACE_ME", "disposable-fixture-only"):
        name = "redis-compat-" + uuid4().hex[:12]
        with tempfile.TemporaryDirectory(prefix="redis-compat-") as directory:
            credentials = Path(directory)
            credentials.chmod(0o755)
            secret = credentials / "REDIS_PASSWORD"
            secret.write_text(password + "\n")
            secret.chmod(0o444)
            try:
                run("docker", "run", "--detach", "--name", name, "--network", "none", "--read-only",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534",
                    "--memory", "128m", "--cpus", "1",
                    "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m,uid=65534,gid=65534",
                    "--tmpfs", "/data:rw,nosuid,nodev,size=32m,uid=65534,gid=65534",
                    "--volume", f"{credentials}:/run/secrets/affine:ro", "--entrypoint", command[0],
                    IMAGE.removeprefix("harbor.stinkyboi.com/mirror/"), *command[1:])
                for _ in range(30):
                    running = run("docker", "inspect", "--format", "{{.State.Running}}", name) == "true"
                    probe = subprocess.run(["docker", "exec", name, *container["readinessProbe"]["exec"]["command"]],
                                           capture_output=True, timeout=10)
                    if not running or probe.returncode == 0:
                        break
                    time.sleep(1)
                if password != "disposable-fixture-only":
                    assert not running, "Invalid credential started Redis"
                    assert run("docker", "inspect", "--format", "{{.State.ExitCode}}", name) != "0"
                    continue
                assert running and probe.returncode == 0, "Authenticated readiness failed"
                run("docker", "exec", name, *container["livenessProbe"]["exec"]["command"])
                cli = ["docker", "exec", name, "redis-cli", "--raw", "--no-auth-warning", "-a", password]
                assert run(*cli, "SET", "fixture", "retained-value") == "OK"
                assert run(*cli, "GET", "fixture") == "retained-value"
                assert run(*cli, "HSET", "fixture-hash", "field", "value") == "1"
                assert run(*cli, "HGET", "fixture-hash", "field") == "value"
                assert run(*cli, "LPUSH", "fixture-list", "job") == "1"
                assert run(*cli, "RPOP", "fixture-list") == "job"
                assert "NOAUTH" in run("docker", "exec", name, "redis-cli", "--raw", "PING")
                wrong = subprocess.run(["docker", "exec", name, "redis-cli", "--no-auth-warning", "-a", "wrong", "PING"],
                                       capture_output=True, text=True, timeout=10)
                assert "WRONGPASS" in wrong.stdout + wrong.stderr
                assert run(*cli, "CONFIG", "GET", "appendonly") == "appendonly\nno"
                assert run(*cli, "CONFIG", "GET", "save") == "save"
                run("docker", "exec", name, "/bin/sh", "-ec", "test $(stat -c %a /tmp/redis.conf) = 600")
                print("AFFiNE Redis UID 65534 startup/probes, auth denial, cache operations and disabled persistence passed")
            finally:
                subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=30, check=False)


if __name__ == "__main__":
    main()
