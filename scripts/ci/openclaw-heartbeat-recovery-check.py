#!/usr/bin/env python3
"""Run the one-shot recovery entrypoint against isolated state/API boundaries."""
import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

source = Path("scripts/openclaw-recover-heartbeat-20260906.py").read_text()
session = "55f4becb-e659-4d6b-b7d5-ccca2a475d5a"
thread = "01a07504-130b-7043-b7e6-059556b7254c"


class Database:
    def __init__(self, identity=session, status="failed", count=244, tamper=False):
        self.identity, self.status, self.count, self.tamper = identity, status, count, tamper

    def execute(self, statement, params):
        assert statement.startswith("SELECT "), "Direct database mutation is forbidden"
        if "session_nodes" in statement:
            assert params == ("agent:main:main",)
            return SimpleNamespace(fetchone=lambda: (
                self.identity, json.dumps({"status": self.status})))
        assert params == (session,)
        rows = [(seq, "changed" if self.tamper else "private fixture") for seq in range(self.count)]
        return SimpleNamespace(fetchall=lambda: rows) if "ORDER BY" in statement else rows

    def close(self):
        pass


def run(before=None, after=None, mode="--recover", api_ok=True, version="2026.9.1", log=None):
    def read_text(path):
        if str(path) == "/app/package.json":
            return json.dumps({"version": version})
        return log if log is not None else f"thread not loaded: {thread}"

    def gateway(argv, **options):
        assert argv[:4] == ["openclaw", "gateway", "call", "sessions.reset"]
        assert json.loads(argv[5]) == {"key": "agent:main:main", "agentId": "main", "reason": "reset"}
        assert options["timeout"] == 180 and options["capture_output"]
        return SimpleNamespace(returncode=0 if api_ok else 1, stdout='{"ok":true}')

    output = io.StringIO()
    error = None
    with patch("pathlib.Path.read_text", read_text), \
            patch("sqlite3.connect", side_effect=[before or Database(), after or Database()]), \
            patch("subprocess.run", side_effect=gateway) as calls, \
            patch("sys.argv", ["-", mode]), contextlib.redirect_stdout(output):
        try:
            exec(compile(source, "recovery", "exec"), {"__name__": "__main__"})
        except (AssertionError, SystemExit) as exc:
            error = exc
    assert "private fixture" not in output.getvalue()
    return error, calls.call_count


for options in [
    {"before": Database(identity="different-session")},
    {"before": Database(status="running")},
    {"before": Database(count=245)},
    {"version": "2026.9.2"},
    {"log": "unrelated failure"},
    {"mode": "--check"},
]:
    error, calls = run(**options)
    assert error is not None and calls == 0
assert run() == (None, 1)
assert run(api_ok=False)[0] is not None
assert run(after=Database(tamper=True))[0] is not None
print("OpenClaw one-shot recovery: exact incident guards, public API, transcript preservation passed")
