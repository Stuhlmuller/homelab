"""Offline checks for the exact-host macOS carrier installation boundary."""
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("carrier", root / "scripts/octelium-macos-api-carrier.py")
carrier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(carrier)
original = "127.0.0.1 localhost\n# octelium-api.stinkyboi.com is managed separately\n"
installed = carrier.hosts_content(original, True)
assert carrier.hosts_content(installed, True) == installed
assert carrier.hosts_content(installed, False) == original
assert carrier.hosts_content(original, False) == original
assert f"127.0.0.1 {carrier.HOST} {carrier.MARKER}" in installed
try:
    carrier.hosts_content(original + f"10.1.0.1 {carrier.HOST}\n", True)
except ValueError:
    pass
else:
    raise AssertionError("An unrelated hosts entry must not be overwritten")
print("macOS carrier hosts checks passed")

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "hosts"
    path.write_text(original)
    path.chmod(0o640)
    carrier.replace_hosts(path, installed)
    assert path.read_text() == installed
    assert path.stat().st_mode & 0o777 == 0o640
    assert list(Path(directory).iterdir()) == [path]

# Apple's curl emits a trailing space on the HTTP/2 status line.
for protocol in ("application/grpc", "application/grpc-web+proto"):
    response = f"HTTP/2 200 \r\ncontent-type: {protocol}\r\ngrpc-status: 16\r\n\r\n"
    with patch.object(carrier.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=response)):
        assert carrier.probe(protocol)
    with patch.object(carrier.subprocess, "run", return_value=SimpleNamespace(returncode=60, stdout=response)):
        assert not carrier.probe(protocol), "TLS failures must fail closed"
    with patch.object(carrier.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=response.replace("200 ", "403 "))):
        assert not carrier.probe(protocol)
print("macOS curl status-line and TLS failure checks passed")

# The migration probe bypasses the owned loopback hosts entry, but keeps TLS verification.
with patch.object(carrier.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=response)) as run:
    carrier.probe("application/grpc-web+proto", "100.100.10.20")
    command = run.call_args.args[0]
    assert f"{carrier.HOST}:443:100.100.10.20:443" in command
    assert "--insecure" not in command

with tempfile.TemporaryDirectory() as directory:
    plist = Path(directory) / f"{carrier.LABEL}.plist"
    content = carrier.plistlib.dumps({"Label": carrier.LABEL, "ProgramArguments": ["cloudflared", carrier.TRANSPORT]})
    plist.write_bytes(content)
    with patch.object(carrier, "PLIST", plist):
        carrier.migration_backup(installed)
        carrier.migration_backup(original)
    assert plist.with_suffix(".plist.before-tailscale").read_bytes() == content
    assert plist.with_suffix(".hosts.before-tailscale").read_text() == f"127.0.0.1 {carrier.HOST} {carrier.MARKER}\n"
    assert plist.with_suffix(".plist.before-tailscale").stat().st_mode & 0o777 == 0o600
print("Mesh preflight and exact owned carrier backup checks passed")

# Both address families must pass strict TLS; the final probe must use OS DNS.
with patch.object(carrier.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=response)) as run:
    carrier.probe("application/grpc-web+proto", "fd7a:115c:a1e0::1234")
    assert f"{carrier.HOST}:443:[fd7a:115c:a1e0::1234]:443" in run.call_args.args[0]
    carrier.probe("application/grpc-web+proto", None)
    assert "--connect-to" not in run.call_args.args[0]

addresses = {"100.100.10.20", "fd7a:115c:a1e0::1234"}
dns_header = ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n"
answers = [SimpleNamespace(stdout=dns_header + f"{carrier.HOST}. 60 IN A 100.100.10.20\n"),
           SimpleNamespace(stdout=dns_header + f"{carrier.HOST}. 60 IN AAAA fd7a:115c:a1e0::1234\n")]
with patch.object(carrier.subprocess, "run", side_effect=answers) as dns:
    assert carrier.public_addresses() == addresses
    assert all(call.args[0][:3] == ["/usr/bin/dig", "@1.1.1.1", carrier.HOST] for call in dns.call_args_list)
for invalid in ("status: SERVFAIL,", dns_header + f"{carrier.HOST}. 60 IN CNAME wrong.ts.net.\n"):
    with patch.object(carrier.subprocess, "run", return_value=SimpleNamespace(stdout=invalid)):
        try:
            carrier.public_addresses()
        except RuntimeError:
            pass
        else:
            raise AssertionError("Unverified DNS responses must not pass")
for failure in (None, "public-dns", "native-dns", "native-tls"):
    with tempfile.TemporaryDirectory() as directory:
        hosts = Path(directory) / "hosts"
        hosts.write_text(installed)
        plist = Path(directory) / "carrier.plist"
        plist.write_bytes(content)
        plist.chmod(0o640)
        # A stale earlier backup must never be restored by this invocation.
        plist.with_suffix(".plist.before-tailscale").write_bytes(b"stale")
        def probe(protocol, address):
            return not (failure == "native-tls" and address is None)
        native = [(2, 1, 6, "", ("127.0.0.1" if failure == "native-dns" else "100.100.10.20", 443))]
        with patch.object(carrier, "PLIST", plist), \
             patch.object(carrier, "public_addresses", return_value={"1.1.1.1"} if failure == "public-dns" else addresses), \
             patch.object(carrier, "probe", side_effect=probe) as probes, \
             patch.object(carrier.socket, "getaddrinfo", return_value=native), \
             patch.object(carrier, "flush_dns"), patch.object(carrier, "run") as run, \
             patch.object(carrier.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            try:
                carrier.migrate_to_tailscale(hosts, addresses, True)
            except RuntimeError:
                assert failure is not None
                assert hosts.read_text() == installed
                assert plist.read_bytes() == content
                assert plist.stat().st_mode & 0o777 == 0o640
                run.assert_not_called()
            else:
                assert failure is None
                assert hosts.read_text() == original
                assert not plist.exists()
                assert all((protocol, address) in [call.args for call in probes.call_args_list]
                           for protocol in ("application/grpc", "application/grpc-web+proto")
                           for address in (*addresses, None))
                run.assert_called_once_with("launchctl", "bootout", f"system/{carrier.LABEL}")
        assert plist.with_suffix(".plist.before-tailscale").read_bytes() == b"stale"
print("Dual-stack public DNS, native canonical API and exact rollback checks passed")
