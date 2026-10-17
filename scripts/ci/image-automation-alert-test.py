#!/usr/bin/env python3
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location("alert", Path(__file__).with_name("image-automation-alert.py"))
alert = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alert)

now = datetime(2026, 10, 6, 0, 10, tzinfo=timezone.utc)
state = {"applications": {"pilot": {
    "outcome": "failed", "stage": "health", "observed_at": "2026-10-06T00:00:00+00:00",
    "deadline_minutes": 5, "failed_digest": "sha256:" + "a" * 64,
    "known_good_digest": "sha256:" + "b" * 64, "pause_reason": "health failed"}}}
payloads = alert.alerts(state, now, "https://example.invalid/run/1")
assert payloads[0]["application"] == "pilot"
assert payloads[0]["failed_digest"].startswith("sha256:")
assert payloads[0]["run_url"].endswith("/run/1")
assert alert.alerts({"applications": {"pilot": {"outcome": "observing"}}}, now) == []
print("image automation alert checks passed")
