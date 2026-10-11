#!/usr/bin/env python3
"""Test pinned PostgreSQL migration bytes on disposable, isolated Docker fixtures."""

import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

TARGET = "cgr.dev/chainguard/postgres@sha256:b409d66dd4c3e7138a7e06ebdfe46966843e9e1a9322cb3b20a13928011ad398"
SOURCES = (
    ("docker.io/library/postgres@sha256:70b9c8977b5fb87bd55c9e29472d778d76d56a6266143d47259da13d78a72afa", 65534),
    ("docker.io/library/postgres@sha256:3725f4e2499eef5134592b3b4ab79a543ed7f8e533b05b5b637af926630f6650", 999),
)


def run(*args, **kwargs):
    result = subprocess.run(args, text=True, capture_output=True, timeout=90, **kwargs)
    if result.returncode:
        raise RuntimeError(f"Fixture command failed ({result.returncode}): " + result.stdout + result.stderr)
    return result.stdout


def database(image, uid, secrets, names):
    name = "postgres-compat-" + uuid4().hex[:12]
    # Register only our generated name before creation so partial startup cleans up.
    names.append(name)
    run("docker", "run", "--detach", "--name", name, "--network", "none",
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", f"{uid}:{uid}", "--memory", "512m", "--cpus", "1",
        "--tmpfs", f"/data:rw,nosuid,nodev,size=256m,uid={uid},gid={uid},mode=0700",
        "--tmpfs", f"/var/run/postgresql:rw,nosuid,nodev,size=16m,uid={uid},gid={uid},mode=0700",
        "--tmpfs", f"/tmp:rw,nosuid,nodev,size=32m,uid={uid},gid={uid},mode=0700",
        "--volume", f"{secrets}:/fixture:ro",
        "--env", "PGDATA=/data/pgdata", "--env", "POSTGRES_USER_FILE=/fixture/user",
        "--env", "POSTGRES_DB_FILE=/fixture/database", "--env", "POSTGRES_PASSWORD_FILE=/fixture/password",
        # Wolfi clients default to /tmp; Debian clients default to /var/run/postgresql.
        image, "-c", "unix_socket_directories=/tmp,/var/run/postgresql")
    for _ in range(60):
        ready = subprocess.run(["docker", "exec", name, "pg_isready", "-U", "fixture", "-d", "fixture"],
                               capture_output=True, text=True, timeout=10)
        if ready.returncode == 0 and run("docker", "exec", name, "cat", "/proc/1/comm").strip() == "postgres":
            version = run("docker", "exec", name, "psql", "-U", "fixture", "-d", "fixture",
                          "-Atqc", "SHOW server_version")
            print(f"Started {image} UID {uid}: PostgreSQL {version.strip()}", flush=True)
            return name
        state = run("docker", "inspect", "--format", "{{.State.Running}}", name).strip()
        if state != "true":
            logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True, timeout=10)
            raise RuntimeError(f"Startup failed at UID {uid}: " + logs.stdout + logs.stderr)
        time.sleep(1)
    raise RuntimeError(f"Startup timed out at UID {uid}")


def sql(name, statement):
    return run("docker", "exec", name, "psql", "-X", "-v", "ON_ERROR_STOP=1",
               "-U", "fixture", "-d", "fixture", "-Atqc", statement).strip()


def main():
    names = []
    try:
        with tempfile.TemporaryDirectory(prefix="postgres-compat-") as directory:
            secrets = Path(directory)
            secrets.chmod(0o755)
            for key, value in (("user", "fixture"), ("database", "fixture"), ("password", "disposable-fixture-only")):
                path = secrets / key
                path.write_text(value + "\n")
                path.chmod(0o444)
            for image, uid in SOURCES:
                source = database(image, uid, secrets, names)
                sql(source, "CREATE ROLE app_reader; CREATE TABLE retained(id bigserial PRIMARY KEY, payload jsonb NOT NULL); "
                    "INSERT INTO retained(payload) VALUES ('{\"text\":\"retained unicode λ\",\"n\":42}'); "
                    "GRANT SELECT ON retained TO app_reader;")
                dump = run("docker", "exec", source, "pg_dump", "-U", "fixture", "-d", "fixture")
                target = database(TARGET, uid, secrets, names)
                sql(target, "CREATE ROLE app_reader")
                run("docker", "exec", "--interactive", target, "psql", "-X", "-v", "ON_ERROR_STOP=1",
                    "-U", "fixture", "-d", "fixture", input=dump)
                assert sql(target, "SELECT payload->>'text' FROM retained WHERE id=1") == "retained unicode λ"
                assert sql(target, "SET ROLE app_reader; SELECT count(*) FROM retained") == "1"
                assert sql(target, "INSERT INTO retained(payload) VALUES ('{}') RETURNING id") == "2"
                assert sql(target, "SELECT count(*) FROM retained") == "2"
                print(f"Logical restore and retained role/data/sequence passed at UID {uid}", flush=True)
    finally:
        for name in names:
            subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=30, check=False)


if __name__ == "__main__":
    main()
