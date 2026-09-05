#!/usr/bin/env python3
"""Install the official Codex plugin matching the pinned gateway release."""
import json
import subprocess
import time
from pathlib import Path

VERSION = "2026.9.1"
SPEC = f"@openclaw/codex@{VERSION}"


def installed():
    result = subprocess.run(
        ["openclaw", "plugins", "inspect", "codex", "--runtime", "--json"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if result.returncode:
        return False
    try:
        report = json.loads(result.stdout)
        plugin = report["plugin"]
        install = report.get("install") or {}
        package = json.loads((Path(plugin["rootDir"]) / "package.json").read_text())
        return (plugin.get("id") == "codex" and plugin.get("origin") == "global"
                and install.get("source") == "npm" and install.get("spec") == SPEC
                and install.get("version") == VERSION
                and package.get("name") == "@openclaw/codex"
                and package.get("version") == VERSION)
    except (ValueError, KeyError, OSError):
        return False


if __name__ == "__main__":
    for delay in (0, 5, 15):
        if installed():
            break
        time.sleep(delay)
        subprocess.run(
            ["openclaw", "plugins", "install", f"npm:{SPEC}",
             "--pin", "--force", "--accept-capabilities"],
            timeout=300, check=False,
        )
    if not installed():
        raise SystemExit("Exact Codex plugin verification failed")
