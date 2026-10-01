#!/usr/bin/env python3
"""Keep Multica's authenticated Octelium connection running under user launchd."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

LABEL = "com.stuhlmuller.multica-octelium"
API = "http://127.0.0.1:18080"


def launch_config(binary):
    return {
        "Label": LABEL,
        "ProgramArguments": [binary, "connect", "--domain", "stinkyboi.com",
                             "--implementation", "gvisor", "--ip-mode", "both", "--no-dns",
                             "--publish", "multica:127.0.0.1:18080"],
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
    domain = f"gui/{os.getuid()}"
    plist = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    running = subprocess.run(["launchctl", "print", f"{domain}/{LABEL}"], capture_output=True).returncode == 0
    if running:
        subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], check=True)
    plist.write_bytes(plistlib.dumps(launch_config(binary)))
    plist.chmod(0o644)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(30):
        try:
            with opener.open(API, timeout=2) as response:
                if response.status == 200:
                    break
        except (OSError, urllib.error.URLError):
            pass
        if attempt == 29:
            raise SystemExit("Octelium route is not ready; desktop config unchanged. Check login and gateway reachability.")
        time.sleep(1)
    configure_desktop(Path.home() / ".multica")
    print("Multica Octelium route ready; desktop endpoint configured. Restart Multica to load it.")


if __name__ == "__main__":
    main()
