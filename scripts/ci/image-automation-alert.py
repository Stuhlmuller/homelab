#!/usr/bin/env python3
"""Emit bounded image-automation alerts without exposing credentials."""
import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "scripts/config/image-automation-state.json"


def alerts(state, now=None, run_url=""):
    now = now or datetime.now(timezone.utc)
    result = []
    for application, item in state.get("applications", {}).items():
        if item.get("outcome") not in {"failed", "paused"} and not item.get("paused"):
            continue
        observed = item.get("observed_at")
        if observed:
            try:
                age = (now - datetime.fromisoformat(observed)).total_seconds()
            except ValueError:
                age = None
            deadline = int(item.get("deadline_minutes", 5)) * 60
            if age is not None and age < deadline:
                continue
        result.append({
            "application": application,
            "stage": item.get("stage", item.get("outcome", "unknown")),
            "failed_digest": item.get("failed_digest"),
            "known_good_digest": item.get("known_good_digest"),
            "action": item.get("pause_reason", "operator review and recovery evaluation required"),
            "run_url": run_url,
        })
    return result


def send(webhook, payload):
    body = json.dumps({"content": "Image automation alert", "embeds": [{"title": "Image automation", "fields": [
        {"name": key, "value": str(value or "unknown"), "inline": False} for key, value in payload.items()
    ]}]}).encode()
    request = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status not in (200, 204):
            raise RuntimeError("notification dependency returned an unexpected status")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=STATE)
    parser.add_argument("--webhook", default="")
    parser.add_argument("--run-url", default="")
    args = parser.parse_args()
    payloads = alerts(json.loads(args.state.read_text()), run_url=args.run_url)
    print(json.dumps({"alerts": payloads}, sort_keys=True))
    if payloads and not args.webhook:
        raise SystemExit("notification dependency unavailable")
    for payload in payloads:
        send(args.webhook, payload)


if __name__ == "__main__":
    main()
