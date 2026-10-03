"""Run the DNS reconciler against an offline Cloudflare/Octelium fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
script = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "scripts/octelium-gateway-dns.sh"
mock = r'''
import json
from pathlib import Path
import sys
from urllib.parse import urlparse, parse_qs
base = Path(sys.argv[0]).parent
name = Path(sys.argv[0]).name
if name == "aws":
    print("test-only-token")
elif name == "octeliumctl":
    print((base / "gateways.json").read_text())
else:
    args = sys.argv[1:]
    method = args[args.index("-X") + 1]
    url = urlparse(args[-1])
    state = json.loads((base / "dns.json").read_text())
    if method == "GET":
        if url.path.endswith("/zones"):
            result = [{"id": "zone"}]
        else:
            query = parse_qs(url.query)
            result = [r for r in state if r["type"] == query["type"][0] and r["name"] == query["name"][0]]
    else:
        with (base / "writes").open("a") as log:
            log.write(method + "\n")
        if method == "DELETE":
            state = [r for r in state if r["id"] != url.path.rsplit("/", 1)[-1]]
        else:
            record = json.loads(args[args.index("--data") + 1])
            record["id"] = url.path.rsplit("/", 1)[-1] if method == "PUT" else "new-" + record["content"]
            state = [r for r in state if r["id"] != record["id"]] + [record]
        (base / "dns.json").write_text(json.dumps(state))
        result = {}
    print(json.dumps({"success": True, "result": result}))
'''
with tempfile.TemporaryDirectory() as temporary:
    base = Path(temporary)
    for command in ("aws", "curl", "octeliumctl"):
        path = base / command
        path.write_text(f"#!{sys.executable}\n" + mock)
        path.chmod(0o700)
    env = {**os.environ, "PATH": f"{base}:{os.environ['PATH']}"}
    hostname = "_gw-test.example.com"
    for addresses in (["10.1.0.200"], ["10.1.0.200", "10.1.0.201", "2001:db8::1"], []):
        initial = [{"id": "old", "name": hostname, "type": "AAAA", "content": "2001:db8::dead", "ttl": 300, "proxied": False}]
        (base / "dns.json").write_text(json.dumps(initial))
        (base / "gateways.json").write_text(json.dumps({"items": [{"status": {"hostname": hostname, "publicIPs": addresses}}]}))
        (base / "writes").write_text("")
        def run(*args):
            return subprocess.run(["bash", str(script), "--domain", "example.com", "--zone", "example.com", *args], env=env, text=True, capture_output=True, timeout=15)
        dry = run("--dry-run")
        assert not (base / "writes").read_text(), dry.stderr
        result = run()
        if not addresses:
            assert result.returncode != 0
            assert json.loads((base / "dns.json").read_text()) == initial
            continue
        assert result.returncode == 0, result.stderr
        records = json.loads((base / "dns.json").read_text())
        assert {(r["type"], r["content"]) for r in records} == {("AAAA" if ":" in ip else "A", ip) for ip in addresses}, records
        before = (base / "writes").read_text()
        assert run().returncode == 0
        assert (base / "writes").read_text() == before, "second run must not mutate DNS"
assert 'field_manager = "terragrunt-annotations"' in (root / "IaC/modules/kubernetes-node-labels/main.tf").read_text()
print("Gateway DNS checks passed: IPv4, dual-stack, multiple IPs, stale removal, dry-run, idempotence, empty status")
