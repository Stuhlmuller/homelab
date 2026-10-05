"""Offline checks for the exact-host macOS carrier installation boundary."""
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

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

# The user agent must keep the client in the foreground and publish only loopback.
spec = importlib.util.spec_from_file_location("desktop", root / "scripts/multica-desktop-connect.py")
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)
config = desktop.launch_config("/usr/local/bin/octelium")
args = desktop.client_args("/usr/local/bin/octelium")
assert config["KeepAlive"] and config["RunAtLoad"]
assert "--detach" not in args and "--no-dns" in args
assert args[-1] == "multica:127.0.0.1:18080"
with tempfile.TemporaryDirectory() as directory:
    profile = Path(directory)
    original = '{"apiUrl":"http://multica","other":"preserved"}'
    (profile / "desktop.json").write_text(original)
    desktop.configure_desktop(profile)
    desktop.configure_desktop(profile)
    updated = desktop.json.loads((profile / "desktop.json").read_text())
    assert updated == {"apiUrl": desktop.API, "wsUrl": "ws://127.0.0.1:18080/ws", "other": "preserved"}
    assert (profile / "desktop.before-octelium.json").read_text() == original
    assert (profile / "desktop.json").stat().st_mode & 0o777 == 0o600
print("Multica persistent connection and config backup checks passed")

# Reproduce a client that stays alive but never serves HTTP; it must be reaped.
child = Mock()
child.poll.return_value = None
with patch.object(desktop.subprocess, "Popen", return_value=child), \
     patch.object(desktop, "route_ready", return_value=False), \
     patch.object(desktop.time, "monotonic", side_effect=[0, 91]), \
     patch.object(desktop.signal, "signal"):
    desktop.supervise("octelium")
child.terminate.assert_called_once()
child.wait.assert_called_once_with(timeout=5)
print("Live but unresponsive client is terminated for launchd recovery")
