#!/usr/bin/env python3
"""Check the quarantine render; --runtime docker also exercises disposable local data."""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/langfuse"
XML = "clickhouse-log-quarantine.xml"
TABLES = (
    "error_log", "histogram_metric_log", "opentelemetry_span_log",
    "part_log", "query_log", "text_log",
)
SQL_TABLES = ", ".join(f"'{name}'" for name in TABLES)
MOUNT = "/etc/clickhouse-server/config.d/log-quarantine.xml"
PASSWORD = "test"


def command(*args, input=None, timeout=60):
    return subprocess.check_output(args, input=input, text=True, timeout=timeout).strip()


def render(path):
    rendered = command("kustomize", "build", str(path))
    return json.loads(command("yq", "eval-all", "-o=json", "[.]", "-", input=rendered))


def contract(resources):
    deployment, = [item for item in resources if item["kind"] == "Deployment"
                   and item["metadata"]["name"] == "langfuse-clickhouse"]
    pod = deployment["spec"]["template"]["spec"]
    container, = [item for item in pod["containers"] if item["name"] == "clickhouse"]
    mounts = [item for item in container["volumeMounts"]
              if item["mountPath"].startswith("/etc/clickhouse-server/config.d")]
    assert mounts == [{"name": "log-quarantine", "mountPath": MOUNT,
                       "subPath": "log-quarantine.xml", "readOnly": True}], mounts
    volume, = [item for item in pod["volumes"] if item["name"] == "log-quarantine"]
    name = volume["configMap"]["name"]
    assert re.fullmatch(r"langfuse-clickhouse-log-quarantine-[a-z0-9]{10}", name), name
    config, = [item for item in resources if item["kind"] == "ConfigMap"
               and item["metadata"]["name"] == name]
    assert config["metadata"]["namespace"] == deployment["metadata"]["namespace"]
    assert set(config["data"]) == {"log-quarantine.xml"}
    assert re.fullmatch(r"clickhouse/clickhouse-server:[^@]+@sha256:[0-9a-f]{64}",
                        container["image"]), "Runtime must use the rendered immutable image"
    return name, container["image"], config["data"]["log-quarantine.xml"]


def static_check():
    source = (APP / XML).read_text()
    root = ET.fromstring(source)
    assert root.tag == "clickhouse" and not root.attrib
    assert [child.tag for child in root] == [*TABLES, "startup_scripts"]
    for table in TABLES:
        child = root.find(table)
        assert child.attrib == {"remove": "1"} and len(child) == 0
    startup = root.find("startup_scripts")
    assert not startup.attrib
    assert [child.tag for child in startup] == ["throw_on_error", *(["scripts"] * 6)]
    assert startup.findtext("throw_on_error") == "true"
    for table, script in zip(TABLES, startup.findall("scripts"), strict=True):
        assert not script.attrib and [child.tag for child in script] == ["condition", "query"]
        assert script.findtext("condition") == f"EXISTS TABLE system.{table} FORMAT TabSeparated"
        assert script.findtext("query") == f"DETACH TABLE IF EXISTS system.{table} PERMANENTLY SYNC"
    name, image, actual = contract(render(APP))
    assert actual == source, "Rendered XML differs from the reviewed quarantine file"
    with tempfile.TemporaryDirectory(prefix="clickhouse-render-") as directory:
        copy = Path(directory) / "langfuse"
        shutil.copytree(APP, copy)
        (copy / XML).write_text(source + "\n<!-- rollout hash fixture -->\n")
        changed_name, changed_image, _ = contract(render(copy))
        assert name != changed_name and image == changed_image, "Config edit must change pod volume reference"
    print("ClickHouse quarantine XML, mount, image pin, and rollout hash checks passed")
    return image, root


def runtime_check(image, root):
    if not shutil.which("docker"):
        raise SystemExit("Docker runtime unavailable: docker executable not found")
    contexts = json.loads(command("docker", "context", "inspect"))
    endpoint = contexts[0]["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith("unix:///"):
        raise SystemExit("Runtime fixture requires a local Docker Unix socket")
    docker = ["docker", "--host", endpoint]
    assert command(*docker, "info", "--format", "{{.OSType}}") == "linux"
    command(*docker, "pull", image, timeout=600)
    prefix = "clickhouse-quarantine-test-" + uuid.uuid4().hex[:12]
    containers, volumes = [], []

    def sql(name, query):
        return command(*docker, "exec", name, "clickhouse-client", "--password", PASSWORD,
                       "--multiquery", "--query", query)

    def volume(suffix):
        name = prefix + "-" + suffix
        command(*docker, "volume", "create", "--label", "homelab.fixture=clickhouse-quarantine", name)
        volumes.append(name)
        # Only this newly created fixture volume needs initial ownership.
        command(*docker, "run", "--rm", "--network", "none", "--user", "0:0",
                "--mount", f"type=volume,source={name},target=/var/lib/clickhouse",
                "--entrypoint", "/bin/chown", image, "-R", "65534:65534", "/var/lib/clickhouse")
        return name

    def start(suffix, data, config):
        name = prefix + "-" + suffix
        containers.append(name)
        command(*docker, "run", "--detach", "--name", name, "--network", "none",
                "--user", "65534:65534", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--cpus", "2", "--memory", "2g",
                "--label", "homelab.fixture=clickhouse-quarantine",
                "--tmpfs", "/tmp:uid=65534,gid=65534,mode=1777",
                "--tmpfs", "/etc/clickhouse-server/users.d:uid=65534,gid=65534,mode=0700",
                "--tmpfs", "/var/log/clickhouse-server:uid=65534,gid=65534,mode=0700",
                "--env", "CLICKHOUSE_DB=default", "--env", "CLICKHOUSE_USER=default",
                "--env", "CLICKHOUSE_PASSWORD_FILE=/run/secrets/langfuse/clickhouse-password",
                "--env", "CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1",
                "--mount", f"type=bind,source={password_file},target=/run/secrets/langfuse/clickhouse-password,readonly",
                "--mount", f"type=volume,source={data},target=/var/lib/clickhouse",
                "--mount", f"type=bind,source={config},target={MOUNT},readonly",
                image)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            ready = subprocess.run([*docker, "exec", name, "clickhouse-client", "--password", PASSWORD,
                                    "--query", "SELECT 1"],
                                   capture_output=True, text=True, timeout=10)
            if ready.returncode == 0:
                return name
            if command(*docker, "inspect", "--format", "{{.State.Running}}", name) != "true":
                break
            time.sleep(1)
        raise AssertionError("Fixture startup failed:\n" + command(*docker, "logs", "--tail", "40", name))

    def stop(name):
        command(*docker, "stop", "--time", "30", name)
        command(*docker, "rm", "--volumes", name)
        containers.remove(name)

    def files(name, paths):
        hashes = command(*docker, "exec", name, "find", *paths, "-type", "f",
                         "-exec", "sha256sum", "{}", "+")
        assert hashes, "Seeded MergeTree parts must contain data files"
        return sorted(hashes.splitlines())

    def verify(name, paths, hashes):
        assert sql(name, f"SELECT count() FROM system.tables WHERE database='system' "
                         f"AND name IN ({SQL_TABLES})") == "0"
        detached = sql(name, f"SELECT table, is_permanently FROM system.detached_tables "
                            f"WHERE database='system' AND table IN ({SQL_TABLES}) ORDER BY table")
        assert detached.splitlines() == [f"{table}\t1" for table in sorted(TABLES)], detached
        assert sql(name, "SELECT marker FROM default.quarantine_sentinel") == "424242"
        assert files(name, paths) == hashes, "Quarantine modified or deleted seeded data parts"

    try:
        with tempfile.TemporaryDirectory(prefix="clickhouse-quarantine-") as directory:
            password_file = Path(directory) / "password"
            password_file.write_text(PASSWORD)
            password_file.chmod(0o644)  # Synthetic fixture credential, readable by UID 65534.
            seed = Path(directory) / "seed.xml"
            baseline = ET.Element("clickhouse")
            for table in TABLES:
                baseline.append(root.find(table))
            ET.ElementTree(baseline).write(seed, encoding="unicode")
            data = volume("data")
            name = start("seed", data, seed)
            for number, table in enumerate(TABLES):
                sql(name, f"CREATE TABLE system.{table} (marker UInt64) ENGINE=MergeTree ORDER BY marker; "
                          f"INSERT INTO system.{table} VALUES ({number})")
            sql(name, "CREATE TABLE default.quarantine_sentinel (marker UInt64) ENGINE=MergeTree ORDER BY marker; "
                      "INSERT INTO default.quarantine_sentinel VALUES (424242)")
            paths = sql(name, f"SELECT path FROM system.parts WHERE database='system' AND active "
                              f"AND table IN ({SQL_TABLES}) ORDER BY table").splitlines()
            assert len(paths) == len(TABLES), paths
            hashes = files(name, paths)
            stop(name)
            for suffix in ("quarantine", "repeat"):
                name = start(suffix, data, APP / XML)
                verify(name, paths, hashes)
                stop(name)
            name = start("fresh", volume("fresh"), APP / XML)
            assert sql(name, f"SELECT count() FROM system.tables WHERE database='system' "
                             f"AND name IN ({SQL_TABLES})") == "0"
            assert sql(name, "SELECT count() FROM system.detached_tables") == "0"
            stop(name)
    finally:
        failures = []
        for name in containers:
            present = subprocess.run([*docker, "container", "inspect", name], capture_output=True)
            if present.returncode == 0:
                result = subprocess.run([*docker, "rm", "--force", "--volumes", name])
                if result.returncode:
                    failures.append(name)
        for name in volumes:
            result = subprocess.run([*docker, "volume", "rm", name])
            if result.returncode:
                failures.append(name)
        assert not failures, f"Fixture cleanup failed: {failures}"
    print("ClickHouse runtime: six permanent detaches, retained data, intact sentinel, repeat and fresh boots passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=["docker"], help="Also run the local Docker fixture")
    arguments = parser.parse_args()
    pinned_image, config_root = static_check()
    if arguments.runtime:
        runtime_check(pinned_image, config_root)
