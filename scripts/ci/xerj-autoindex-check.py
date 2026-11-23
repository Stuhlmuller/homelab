"""Exercise the pinned XERJ release against the actual Octelium manifest."""

import json
import os
import signal
import socket
import sys
import time
from pathlib import Path
from shutil import copyfile
from subprocess import DEVNULL, Popen, run
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


loopback = build_opener(ProxyHandler({}))


def search(url, key, index, query):
    request = Request(
        f"{url}/{index}/_search",
        data=json.dumps(query).encode(),
        headers={"Authorization": f"ApiKey {key}", "Content-Type": "application/json"},
    )
    with loopback.open(request, timeout=3) as response:
        return json.load(response)["hits"]["hits"]


def mcp_search(workspace, environment, index, field):
    requests = [
        {"id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "homelab-check", "version": "1"},
        }},
        {"method": "notifications/initialized"},
        {"id": 2, "method": "tools/call", "params": {
            "name": "xerj_search",
            "arguments": {"index": index, "query_dsl": {"exists": {"field": field}}},
        }},
    ]
    result = run(
        ["xerj", "mcp", "--disable-feedback"],
        input="".join(json.dumps({"jsonrpc": "2.0", **request}) + "\n" for request in requests),
        capture_output=True,
        text=True,
        cwd=workspace,
        env=environment,
        timeout=20,
        check=True,
    )
    replies = {entry["id"]: entry["result"] for entry in map(json.loads, result.stdout.splitlines())}
    assert replies[1]["serverInfo"]["name"] == "xerj-mcp", "expected an MCP handshake"
    return replies[2]


def check(manifest, workspace):
    fixture = workspace / "source/clusters/homelab/apps/octelium-enterprise/resources.yaml"
    fixture.parent.mkdir(parents=True)
    copyfile(manifest, fixture)

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    storage = workspace / "node-data"
    temporary = workspace / "temp"
    temporary.mkdir()
    # Use XERJ's home resolution with only the disposable fixture's data.
    # Keep the recorded node outside TMPDIR so the stock MCP would restart it.
    environment = {
        "PATH": os.environ["PATH"], "HOME": str(workspace), "TMPDIR": str(temporary),
        "XERJ_AUTOSTART_TIMEOUT_SECS": "10",
    }
    with Popen(
        ["xerj", "--disable-feedback", "--bind", "127.0.0.1", "--port", str(port),
         "--data-dir", str(storage)],
        cwd=workspace,
        env=environment,
        stdout=DEVNULL,
        # The first-launch banner contains an ephemeral owner-claim token.
        stderr=DEVNULL,
    ) as node:
        try:
            key_path = storage / "admin.key"
            deadline = time.monotonic() + 10
            while (remaining := deadline - time.monotonic()) > 0:
                if node.poll() is not None:
                    raise RuntimeError(f"XERJ exited during startup with status {node.returncode}")
                try:
                    key = key_path.read_text().strip()
                    request = Request(f"{url}/_cluster/health", headers={"Authorization": f"ApiKey {key}"})
                    with loopback.open(request, timeout=min(1, remaining)):
                        break
                except (FileNotFoundError, TimeoutError, URLError):
                    time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            else:
                raise RuntimeError("XERJ did not accept authenticated loopback requests")

            prefix = "homelab-yaml"
            run(
                ["xerj", "autoindex", str(workspace / "source"), "--disable-feedback",
                 "--url", url, "--prefix", prefix, "--state-dir", str(workspace / "state"),
                 "--no-graph", "--workers", "4"],
                cwd=workspace,
                env=environment,
                timeout=60,
                check=True,
            )
            assert search(url, key, "autoindex-catalog", {"size": 1}), "missing committed catalog"
            field = "metadata_annotations_octelium.com/last-upgrade"
            index = f"{prefix}-clusters-homelab"
            hits = search(
                url, key, index,
                {"size": 1, "query": {"exists": {"field": field}}, "sort": [{field: "asc"}]},
            )
            assert hits and hits[0]["_source"][field] and hits[0]["sort"][0] is not None, (
                "missing searchable YAML annotation with a sort value"
            )
            print(f"XERJ committed the catalog and found the sorted {field} field")
            result = mcp_search(workspace, environment, index, field)
            assert not result.get("isError") and field in json.dumps(result), result
        finally:
            node.kill()

    try:
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", port)) != 0, "fixture node is still listening"
        result = mcp_search(workspace, environment, index, field)
        assert result.get("isError"), "MCP should report the stopped node"
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", port)) != 0, "MCP started a stopped node"
    finally:
        launched = json.loads((storage / "node.launch.json").read_text())["pid"]
        if launched != node.pid:
            try:
                os.kill(launched, signal.SIGTERM)
            except ProcessLookupError:
                # The unexpected process exited before cleanup could signal it.
                pass
            raise AssertionError("MCP restarted the node recorded by this fixture")
    print("XERJ MCP authenticated against the running node and left it stopped after shutdown")


with TemporaryDirectory(prefix="xerj-autoindex-") as directory:
    check(Path(sys.argv[1]), Path(directory))
