#!/usr/bin/env python3
"""Idempotently register managed jobs through the running gateway's public CLI."""
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from bootstrap import atomic_write

BUNDLE = Path("/etc/openclaw-assistant")
CONFIG = Path("/data/openclaw/config/openclaw.json")
STATUS = Path("/data/openclaw/assistant-reconciliation.json")


def status(state, detail):
    atomic_write(STATUS, json.dumps({"state": state, "detail": detail,
                                    "updatedAt": datetime.now(timezone.utc).isoformat()}) + "\n")


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
    try:
        destination = owner_destination(json.loads(CONFIG.read_text()))
    except ValueError as error:
        status("deferred", str(error))
        print("Assistant schedules deferred; configure Discord and one owner", flush=True)
        return
    jobs = json.loads((BUNDLE / "jobs.json").read_text())
    status("pending", "Waiting for the gateway automation API")
    deadline = time.monotonic() + 300
    # postStart runs concurrently with the normal gateway entrypoint. Each retry
    # converges the same declaration keys; disabled jobs stay disabled upstream.
    for attempt in range(6):
        try:
            for job in jobs:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("scheduler reconciliation deadline exceeded")
                result = subprocess.run(command(job, destination), capture_output=True,
                                        timeout=min(60, remaining), check=False)
                if result.returncode:
                    raise RuntimeError(f"scheduler rejected managed job {job['key']}")
            status("ready", "All three managed homelab automations reconciled")
            print("All three managed homelab automations reconciled", flush=True)
            return
        except (RuntimeError, subprocess.TimeoutExpired):
            # CLI diagnostics can contain private routes; keep them out of logs.
            print(f"Assistant scheduler not ready (attempt {attempt + 1}/6)", flush=True)
            if attempt == 5 or time.monotonic() >= deadline:
                status("failed", "Gateway automation API rejected reconciliation; rerun after repair")
                return  # Keep chat available; readiness of the jobs is verified separately.
            time.sleep(min(10, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    reconcile()
