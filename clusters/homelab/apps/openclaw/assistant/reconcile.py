#!/usr/bin/env python3
"""Idempotently register managed jobs through the running gateway's public CLI."""
import json
import re
import subprocess
import time
from pathlib import Path

BUNDLE = Path("/etc/openclaw-assistant")
CONFIG = Path("/data/openclaw/config/openclaw.json")


def owner_destination(config):
    discord = config.get("channels", {}).get("discord", {})
    if discord.get("enabled") is not True:
        raise ValueError("Discord must be enabled before scheduling owner messages")
    explicit = config.get("commands", {}).get("ownerAllowFrom", [])
    candidates = explicit or discord.get("allowFrom", [])
    owners = set()
    for candidate in candidates:
        match = re.fullmatch(r"(?:discord:)?(?:user:)?([0-9]{15,22})", str(candidate))
        if match:
            owners.add(match[1])
    if len(owners) != 1:
        raise ValueError("configure one explicit Discord owner; never guess a delivery destination")
    return "user:" + owners.pop()


def command(job, destination):
    return [
        "openclaw", "automations", "add",
        "--declaration-key", "homelab:assistant:v1:" + job["key"],
        "--name", job["name"], "--agent", "main", "--session", "isolated",
        "--cron", job["schedule"], "--tz", "America/Los_Angeles",
        "--model", "openai/gpt-6-astra", "--thinking", "medium",
        "--fallbacks", "", "--timeout-seconds", str(job["timeoutSeconds"]),
        "--message", job["message"], "--announce", "--channel", "discord",
        "--to", destination, "--timeout", "20000",
    ]


def reconcile():
    destination = owner_destination(json.loads(CONFIG.read_text()))
    jobs = json.loads((BUNDLE / "jobs.json").read_text())
    # postStart runs concurrently with the normal gateway entrypoint. Each retry
    # converges the same declaration keys; disabled jobs stay disabled upstream.
    for attempt in range(6):
        try:
            for job in jobs:
                result = subprocess.run(command(job, destination), capture_output=True,
                                        timeout=60, check=False)
                if result.returncode:
                    raise RuntimeError(f"scheduler rejected managed job {job['key']}")
            print("All three managed homelab automations reconciled", flush=True)
            return
        except (RuntimeError, subprocess.TimeoutExpired):
            # CLI diagnostics can contain private routes; keep them out of logs.
            print(f"Assistant scheduler not ready (attempt {attempt + 1}/6)", flush=True)
            if attempt == 5:
                raise RuntimeError("assistant scheduler reconciliation failed") from None
            time.sleep(10)


if __name__ == "__main__":
    reconcile()
