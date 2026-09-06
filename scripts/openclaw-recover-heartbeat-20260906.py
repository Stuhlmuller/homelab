#!/usr/bin/env python3
"""One-shot recovery of the observed missing main-session Codex thread.

Run inside OpenClaw via stdin. Uses the public session reset lifecycle, which
retains the transcript and clears active model context plus the harness binding.
No direct database writes. This is intentionally not a recurring repair.
"""
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

SESSION = "55f4becb-e659-4d6b-b7d5-ccca2a475d5a"
KEY = "agent:main:main"
THREAD = "01a07504-130b-7043-b7e6-059556b7254c"
mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
assert mode in ("--check", "--recover"), "Expected --check or --recover"
assert json.loads(Path("/app/package.json").read_text())["version"] == "2026.9.1"
db = sqlite3.connect(
    "file:/data/openclaw/agents/main/agent/openclaw-agent.sqlite?mode=ro", uri=True)
row = db.execute("SELECT current_session_id,entry_json FROM session_nodes WHERE session_key=?",
                 (KEY,)).fetchone()
assert row and row[0] == SESSION, "Session identity changed; do not reset another session"
entry = json.loads(row[1])
assert entry.get("status") == "failed", "Session is no longer failed; inspect before resetting"
assert f"thread not loaded: {THREAD}" in Path(
    "/tmp/openclaw/openclaw-2026-09-06.log").read_text(), "Expected native failure not observed"
events = db.execute("SELECT seq,event_json FROM transcript_events WHERE session_id=? ORDER BY seq",
                    (SESSION,)).fetchall()
assert len(events) == 244, "Transcript changed since diagnosis; do not reset later work"
fingerprints = {seq: hashlib.sha256(text.encode()).digest() for seq, text in events}
db.close()
if mode == "--check":
    print(f"FAIL: observed main-session native thread missing; {len(events)} transcript events retained")
    sys.exit(1)
result = subprocess.run([
    "openclaw", "gateway", "call", "sessions.reset", "--params",
    json.dumps({"key": KEY, "agentId": "main", "reason": "reset"}),
    "--json", "--timeout", "60000",
], capture_output=True, text=True, timeout=180, check=False)
assert result.returncode == 0, "Gateway rejected reset; inspect private gateway logs"
assert json.loads(result.stdout).get("ok") is True, "Gateway did not confirm reset"
db = sqlite3.connect(
    "file:/data/openclaw/agents/main/agent/openclaw-agent.sqlite?mode=ro", uri=True)
retained = {seq: hashlib.sha256(text.encode()).digest() for seq, text in db.execute(
    "SELECT seq,event_json FROM transcript_events WHERE session_id=?", (SESSION,))}
db.close()
assert all(retained.get(seq) == digest for seq, digest in fingerprints.items()), "Transcript verification failed"
print(f"PASS: broken runtime context reset; all {len(events)} original transcript events unchanged")
