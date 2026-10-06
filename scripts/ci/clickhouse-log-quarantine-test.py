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
SCRIPT = "quarantine-system-logs.sh"
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
    assert deployment["spec"]["strategy"]["type"] == "Recreate", "Init quarantine requires the old server stopped"
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
    wave = "argocd.argoproj.io/sync-wave"
    assert int(config["metadata"].get("annotations", {}).get(wave, "0")) < int(
        deployment["metadata"].get("annotations", {}).get(wave, "0")
    ), "Quarantine config must sync before the Recreate deployment"
    assert set(config["data"]) == {"log-quarantine.xml", SCRIPT}
    assert re.fullmatch(r"clickhouse/clickhouse-server:[^@]+@sha256:[0-9a-f]{64}",
                        container["image"]), "Runtime must use the rendered immutable image"
    init, = pod["initContainers"]
    assert init["image"] == container["image"], "Quarantine must use the exact server image"
    assert init["command"] == ["/bin/sh", "/quarantine/" + SCRIPT]
    assert init["securityContext"] == container["securityContext"]
    assert init["securityContext"]["runAsUser"] == 65534
    assert init["volumeMounts"] == [
        {"name": "data", "mountPath": "/var/lib/clickhouse"},
        {"name": "log-quarantine", "mountPath": "/quarantine", "readOnly": True},
    ]
    data, = [item for item in pod["volumes"] if item["name"] == "data"]
    assert data["persistentVolumeClaim"]["claimName"] == "langfuse-clickhouse-data"
    assert [item for item in container["volumeMounts"] if item["name"] == "data"] == [
        {"name": "data", "mountPath": "/var/lib/clickhouse"}]
    return name, container["image"], config["data"]


def static_check():
    source = (APP / XML).read_text()
    root = ET.fromstring(source)
    assert root.tag == "clickhouse" and not root.attrib
    assert [child.tag for child in root] == list(TABLES), "No SQL startup hook may load corrupt metadata"
    for table in TABLES:
        child = root.find(table)
        assert child.attrib == {"remove": "1"} and len(child) == 0
    command("/bin/sh", "-n", str(APP / SCRIPT))
    name, image, actual = contract(render(APP))
    assert actual == {"log-quarantine.xml": source, SCRIPT: (APP / SCRIPT).read_text()}
    with tempfile.TemporaryDirectory(prefix="clickhouse-render-") as directory:
        copy = Path(directory) / "langfuse"
        shutil.copytree(APP, copy)
        for filename, extra in [(XML, "\n<!-- rollout hash fixture -->\n"), (SCRIPT, "\n# rollout hash fixture\n")]:
            target = copy / filename
            original = target.read_text()
            target.write_text(original + extra)
            changed_name, changed_image, _ = contract(render(copy))
            assert name != changed_name and image == changed_image, "Config edit must change pod volume reference"
            target.write_text(original)
    print("ClickHouse quarantine XML, init container, mount, image pin, wave and rollout hash checks passed")
    return image


def runtime_check(image):
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

    def start(suffix, data, config, *, corrupt=False):
        name = prefix + "-" + suffix
        containers.append(name)
        command(*docker, "run", "--detach", "--name", name, "--network", "none", "--hostname", "localhost",
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
                "--mount", f"type=bind,source={console_file},target=/etc/clickhouse-server/config.d/fixture-console.xml,readonly",
                image)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            # The entrypoint briefly starts a temporary server before execing
            # the final server. SQL readiness alone races that shutdown.
            server = subprocess.run([*docker, "exec", name, "readlink", "/proc/1/exe"],
                                    capture_output=True, text=True, timeout=10)
            ready = subprocess.run([*docker, "exec", name, "clickhouse-client", "--password", PASSWORD,
                                    "--query", "SELECT 1"],
                                   capture_output=True, text=True, timeout=10)
            if ready.returncode == 0 and server.stdout.strip() == "/usr/bin/clickhouse":
                assert not corrupt, "Unquarantined overlapping parts unexpectedly allowed startup"
                return name
            if command(*docker, "inspect", "--format", "{{.State.Running}}", name) != "true":
                if corrupt:
                    assert command(*docker, "inspect", "--format", "{{.State.ExitCode}}", name) != "0"
                    logs = command(*docker, "logs", name)
                    assert re.search(r"intersect|overlap", logs, re.IGNORECASE), logs[-4000:]
                    stop(name)
                    return
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

    def offline(data, script, *args):
        return command(*docker, "run", "--rm", "--network", "none", "--user", "65534:65534",
                       "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                       "--mount", f"type=volume,source={data},target=/var/lib/clickhouse",
                       "--mount", f"type=bind,source={APP / SCRIPT},target=/quarantine/{SCRIPT},readonly",
                       "--entrypoint", "/bin/sh", image, "-eu", "-c", script, "fixture", *args)

    def quarantine(data):
        offline(data, 'exec /bin/sh /quarantine/' + SCRIPT)

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
            console_file = Path(directory) / "console.xml"
            console_file.write_text("<clickhouse><logger><console>1</console></logger></clickhouse>\n")
            password_file = Path(directory) / "password"
            password_file.write_text(PASSWORD)
            password_file.chmod(0o644)  # Synthetic fixture credential, readable by UID 65534.
            data = volume("data")
            name = start("seed", data, APP / XML)
            for number, table in enumerate(TABLES):
                sql(name, f"CREATE TABLE system.{table} (marker UInt64) ENGINE=MergeTree ORDER BY marker; "
                          f"INSERT INTO system.{table} VALUES ({number})")
            sql(name, "CREATE TABLE default.quarantine_sentinel (marker UInt64) ENGINE=MergeTree ORDER BY marker; "
                      "INSERT INTO default.quarantine_sentinel VALUES (424242)")
            parts = sql(name, f"SELECT path FROM system.parts WHERE database='system' AND active "
                              f"AND table IN ({SQL_TABLES}) ORDER BY table").splitlines()
            assert len(parts) == len(TABLES), parts
            paths = sql(name, f"SELECT arrayJoin([data_paths[1], metadata_path]) FROM system.tables WHERE "
                             f"(database='system' AND name IN ({SQL_TABLES})) OR "
                             "(database='default' AND name='quarantine_sentinel') ORDER BY database, name").splitlines()
            assert len(paths) == 2 * (len(TABLES) + 1), paths
            stop(name)
            # Two ranges overlap without either containing the other: native metadata load must reject them.
            offline(data, 'part=${1%/}; base=${part%/*}; mv "$part" "$base/all_1_2_0"; '
                          'cp -a "$base/all_1_2_0" "$base/all_2_3_0"', parts[0])
            start("corrupt", data, APP / XML, corrupt=True)
            # Both guards must reject before creating any marker, even for the last table in the allowlist.
            offline(data, 'alias=/var/lib/clickhouse/metadata/system; target=$(readlink "$alias"); '
                          'directory=$(readlink -f "$alias"); '
                          'ln -sfn /var/lib/clickhouse/store/wrong-system-database "$alias"; '
                          'if /bin/sh /quarantine/quarantine-system-logs.sh; then exit 1; fi; '
                          'test -z "$(find "$directory" -maxdepth 1 -name "*.sql.detached" -print)"; '
                          'ln -sfn "$target" "$alias"')
            offline(data, 'directory=$(readlink -f /var/lib/clickhouse/metadata/system); '
                          'marker="$directory/text_log.sql.detached"; printf guard > "$marker"; '
                          'if /bin/sh /quarantine/quarantine-system-logs.sh; then exit 1; fi; '
                          'test "$(cat "$marker")" = guard; '
                          'test "$(find "$directory" -maxdepth 1 -name "*.sql.detached" | wc -l)" -eq 1; '
                          'rm "$marker"')
            hashes = sorted(offline(data, 'find "$@" -type f -exec sha256sum {} +', *paths).splitlines())
            assert hashes
            for suffix in ("quarantine", "repeat"):
                quarantine(data)
                name = start(suffix, data, APP / XML)
                verify(name, paths, hashes)
                stop(name)
            fresh = volume("fresh")
            quarantine(fresh)
            name = start("fresh", fresh, APP / XML)
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
    print("ClickHouse runtime: corrupt startup rejected; init quarantine retained data and sentinel; repeat/fresh boots passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=["docker"], help="Also run the local Docker fixture")
    arguments = parser.parse_args()
    pinned_image = static_check()
    if arguments.runtime:
        runtime_check(pinned_image)
