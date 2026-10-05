#!/usr/bin/env python3
"""Keep Multica's authenticated Octelium connection running under user launchd."""
import json
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

LABEL = "com.stuhlmuller.multica-octelium"
API = "http://127.0.0.1:18080"


def client_args(binary):
    return [binary, "connect", "--domain", "stinkyboi.com",
            "--implementation", "gvisor", "--ip-mode", "both", "--no-dns",
            "--publish", "multica:127.0.0.1:18080"]


def route_ready():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(API, timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def supervise(binary):
    # launchd restarts this supervisor; a live but wedged client must exit too.
    child = subprocess.Popen(client_args(binary), stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    def stop(_signum, _frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    try:
        deadline = time.monotonic() + 90
        while child.poll() is None:
            if route_ready():
                deadline = time.monotonic() + 30
            elif time.monotonic() >= deadline:
                return
            time.sleep(5)
    finally:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def launch_config(binary):
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, str(Path.home() / ".multica/octelium-client.py"),
                             "--supervise", binary],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "ProcessType": "Background",
    }


def configure_desktop(profile):
    profile.mkdir(mode=0o700, exist_ok=True)
    desktop = profile / "desktop.json"
    backup = profile / "desktop.before-octelium.json"
    config = json.loads(desktop.read_text()) if desktop.exists() else {}
    if desktop.exists() and not backup.exists():
        shutil.copyfile(desktop, backup)
        backup.chmod(0o600)
    config.update(apiUrl=API, wsUrl="ws://127.0.0.1:18080/ws")
    temporary = desktop.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(desktop)


def main():
    if sys.platform != "darwin" or os.geteuid() == 0:
        raise SystemExit("Run as the signed-in macOS user, without sudo")
    binary = shutil.which("octelium")
    if not binary:
        raise SystemExit("Octelium CLI is required")
    profile = Path.home() / ".multica"
    profile.mkdir(mode=0o700, exist_ok=True)
    runner = profile / "octelium-client.py"
    shutil.copyfile(Path(__file__).resolve(), runner)
    runner.chmod(0o700)
    domain = f"gui/{os.getuid()}"
    plist = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    running = subprocess.run(["launchctl", "print", f"{domain}/{LABEL}"], capture_output=True, check=False).returncode == 0
    if running:
        subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], check=True)
    plist.write_bytes(plistlib.dumps(launch_config(binary)))
    plist.chmod(0o644)
    for attempt in range(10):
        result = subprocess.run(["launchctl", "bootstrap", domain, str(plist)], capture_output=True, check=False)
        if result.returncode == 0:
            break
        if attempt == 9:
            raise SystemExit("launchd could not load the client; desktop config unchanged")
        time.sleep(1)  # bootout can return before the previous job finishes exiting.
    for attempt in range(30):
        if route_ready():
            break
        if attempt == 29:
            raise SystemExit("Octelium route is not ready; desktop config unchanged. Check login and gateway reachability.")
        time.sleep(1)
    configure_desktop(Path.home() / ".multica")
    print("Multica Octelium route ready; desktop endpoint configured. Restart Multica to load it.")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--supervise":
        supervise(sys.argv[2])
    else:
        main()
