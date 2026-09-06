#!/usr/bin/env python3
"""Exercise the actual bootstrap migration against disposable, non-secret config."""
import copy
import json
import pathlib
import subprocess
import sys
import tempfile

values = "clusters/homelab/apps/openclaw/values.yaml"
bootstrap = subprocess.check_output(
    ["yq", "-r", '.controllers.openclaw.initContainers."bootstrap-config".command[2]', values],
    text=True,
)
marker = "OPENCLAW_CONFIG_MIGRATION"
migration = bootstrap.split(f"<<'{marker}'\n", 1)[1].split(f"\n{marker}", 1)[0]
assert bootstrap.index('verify_backup_dir "$backup_dir"') < bootstrap.index(migration)
assert bootstrap.index(migration) < bootstrap.index("openclaw_version=")
assert "hooks.maxBodyBytes" not in bootstrap

legacy = {
    "meta": {"lastTouchedAt": "2026-07-01", "lastTouchedVersion": "2026.7.1"},
    "commands": {"ownerDisplay": "raw", "ownerAllowFrom": ["example-owner"]},
    "hooks": {"maxBodyBytes": 65536, "allowRequestSessionKey": False},
    "plugins": {"bundledDiscovery": "allowlist", "allow": ["discord"]},
    "agents": {"defaults": {"models": {"openai/gpt-5.5": {"agentRuntime": {"id": "codex"}}}}},
    "skills": {"allowBundled": ["example-skill"]},
}
expected = copy.deepcopy(legacy)
for section, key in (("meta", "lastTouchedAt"), ("commands", "ownerDisplay"),
                     ("hooks", "maxBodyBytes"), ("plugins", "bundledDiscovery")):
    del expected[section][key]
expected["agents"]["defaults"]["modelPolicy"] = {"allow": ["openai/gpt-5.5"]}

with tempfile.TemporaryDirectory() as directory:
    path = pathlib.Path(directory) / "openclaw.json"
    for original in (legacy, expected, {}, {"agents": {"defaults": {
        "models": {"openai/gpt-5.5": {}}, "modelPolicy": {"allow": []}}}},
        {"meta": {"migrations": {"modelPolicyAllowlist": True}},
         "agents": {"defaults": {"models": {"openai/gpt-5.5": {}}}}}):
        path.write_text(json.dumps(original))
        subprocess.run([sys.executable, "-c", migration, str(path)], check=True)
        assert json.loads(path.read_text()) == (expected if original == legacy else original)
        if original == legacy:
            assert path.stat().st_mode & 0o777 == 0o600
        first = path.read_bytes()
        subprocess.run([sys.executable, "-c", migration, str(path)], check=True)
        assert path.read_bytes() == first
    path.write_text('{"broken":')
    result = subprocess.run([sys.executable, "-c", migration, str(path)], capture_output=True)
    assert result.returncode != 0 and path.read_text() == '{"broken":'
print("OpenClaw config migration: preservation, idempotence, and invalid-input checks passed")

marker = "OPENCLAW_SESSION_REPORT"
gate = bootstrap.split(f"<<'{marker}'\n", 1)[1].split(f"\n{marker}", 1)[0]
known_issue = {"code": "transcript_missing", "sessionKey": "agent:main:healthcheck-20260813"}
clean_report = {"mode": "dry-run", "targets": [{"agentId": "main", "issues": []}],
                "totals": {"issues": 0}}
warning_report = copy.deepcopy(clean_report)
warning_report["targets"][0]["issues"] = [known_issue]
warning_report["totals"]["issues"] = 1
cases = [(clean_report, 0, True), (clean_report, 1, False),
         (warning_report, 1, True), (warning_report, 2, False)]
for field, value in (("code", "transcript_malformed"), ("code", "sqlite_corrupt"),
                     ("sessionKey", "agent:main:real-session")):
    report = copy.deepcopy(warning_report)
    report["targets"][0]["issues"][0][field] = value
    cases.append((report, 1, False))
for field, value in (("mode", "import"), ("targets", []), ("totals", {"issues": 0})):
    report = copy.deepcopy(warning_report)
    report[field] = value
    cases.append((report, 1, False))
report = copy.deepcopy(warning_report)
report["targets"][0]["agentId"] = "other"
cases.append((report, 1, False))
with tempfile.TemporaryDirectory() as directory:
    path = pathlib.Path(directory) / "report.json"
    for report, status, accepted in cases:
        path.write_text(json.dumps(report))
        before = path.read_bytes()
        result = subprocess.run([sys.executable, "-c", gate, str(path), str(status), "dry-run"],
                                capture_output=True)
        assert (result.returncode == 0) == accepted, result.stderr.decode()
        assert path.read_bytes() == before
    path.write_text('{"broken":')
    result = subprocess.run([sys.executable, "-c", gate, str(path), "1", "dry-run"],
                            capture_output=True)
    assert result.returncode != 0
    path.write_text(json.dumps(warning_report))
    helper = bootstrap[bootstrap.index("session_sqlite() {"):]
    helper = helper.split('\nif "$had_existing_state"', 1)[0]
    script = 'OPENCLAW_STATE_DIR="$1"\nfixture="$2"\n'
    script += 'openclaw() { cat "$fixture"; return 1; }\n' + helper
    script += '\nsession_sqlite --session-sqlite dry-run --session-sqlite-all-agents\n'
    subprocess.run(["sh", "-ec", script, "fixture", directory, str(path)],
                   check=True, capture_output=True)
    saved = list((pathlib.Path(directory) / "session-sqlite-reports").iterdir())
    assert len(saved) == 1 and saved[0].stat().st_mode & 0o777 == 0o600
    assert json.loads(saved[0].read_text()) == warning_report
    for _ in range(3):
        subprocess.run(["sh", "-ec", script, "fixture", directory, str(path)],
                       check=True, capture_output=True)
    saved = list((pathlib.Path(directory) / "session-sqlite-reports").iterdir())
    assert len(saved) == 2
    assert all(item.stat().st_mode & 0o777 == 0o600 for item in saved)
    assert all(json.loads(item.read_text()) == warning_report for item in saved)
print("OpenClaw session report: known warning accepted; unexpected issues and failures rejected")

marker = "OPENCLAW_SESSION_PRESERVATION"
preservation = bootstrap.split(f"<<'{marker}'\n", 1)[1].split(f"\n{marker}", 1)[0]
assert bootstrap.index("session_preservation snapshot") < bootstrap.index(
    "session_sqlite --session-sqlite import")
assert bootstrap.index("session_preservation verify") < bootstrap.index(
    "printf 'session SQLite migration imported and inspected")
with tempfile.TemporaryDirectory() as directory:
    import sqlite3

    root = pathlib.Path(directory)
    store = root / "sessions.json"
    database = root / "sessions.sqlite"
    report_path = root / "report.json"
    expected_path = root / "expected-sessions.json"
    key = "agent:main:healthcheck-20260813"
    store.write_text(json.dumps({key: {"sessionId": "original-id"}}))
    report_path.write_text(json.dumps({"targets": [{"storePath": str(store),
        "sqlitePath": str(database), "legacyEntries": 1}]}))

    def preserve(mode):
        return subprocess.run([sys.executable, "-c", preservation, mode,
                               str(report_path), str(expected_path)], capture_output=True)

    assert preserve("snapshot").returncode == 0
    assert expected_path.stat().st_mode & 0o777 == 0o600
    inventory = expected_path.read_bytes()
    store.unlink()  # Upstream archives the legacy store after import.
    assert preserve("snapshot").returncode == 0
    assert expected_path.read_bytes() == inventory  # Restart cannot erase expectations.
    assert preserve("verify").returncode != 0 and not database.exists()
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE session_nodes (session_key TEXT, current_session_id TEXT)")
    assert preserve("verify").returncode != 0
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO session_nodes VALUES (?, ?)", (key, "wrong-id"))
    assert preserve("verify").returncode != 0
    with sqlite3.connect(database) as db:
        db.execute("UPDATE session_nodes SET current_session_id = 'original-id'")
    assert preserve("verify").returncode == 0
    assert expected_path.read_bytes() == inventory
print("OpenClaw import preservation: missing/changed sessions rejected; restart inventory retained")

doctor_setup = bootstrap[bootstrap.index('doctor_marker="$OPENCLAW_STATE_DIR/') : bootstrap.index('had_existing_state=false')]
doctor = bootstrap[bootstrap.rindex('if [ ! -s "$doctor_marker" ]; then') :]
assert 'timeout --signal=TERM --kill-after=30s 10m' in doctor
for failure in ("backup", "doctor", "timeout", "preservation", "validate", "none"):
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        (root / "sessions-migrated").write_text("complete\n")
        original_config = '{"skills":{"allowBundled":["fixture-skill"]}}\n'
        (root / "config.json").write_text(original_config)
        harness = '''OPENCLAW_STATE_DIR="$1"
OPENCLAW_CONFIG_PATH="$1/config.json"
failure="$2"
had_existing_state=true
backup_dir="$1/backup"
migration_marker="$1/sessions-migrated"
verify_backup_dir() { test "$failure" != backup; }
session_preservation() { test "$failure" != preservation; }
timeout() {
  test "$failure" != timeout || return 124
  shift 3
  "$@"
}
openclaw() {
  if [ "$1" = doctor ]; then
    printf '{"doctorChangedPolicy":true}\n' > "$OPENCLAW_CONFIG_PATH"
    printf 'private diagnostic fixture\n'
    test "$failure" != doctor
  else
    test "$failure" != validate
  fi
}
'''
        result = subprocess.run(["sh", "-ec", harness + doctor_setup + doctor, "fixture", directory, failure],
                                capture_output=True)
        marker_path = root / ".doctor-state-migrated-to-2026.8.2"
        assert (result.returncode == 0) == (failure == "none")
        assert marker_path.exists() == (failure == "none")
        assert (root / "config.json").read_text() == original_config
        assert b"private diagnostic fixture" not in result.stdout + result.stderr
        report_path = root / "doctor-state-reports/latest.log"
        if report_path.exists():
            assert report_path.stat().st_mode & 0o777 == 0o600
        if failure == "doctor":
            # Simulate termination after doctor rewrites config but before restore.
            (root / "config.json").write_text('{"interruptedRewrite":true}')
            subprocess.run(["sh", "-ec", harness + doctor_setup, "fixture", directory, failure],
                           check=True, capture_output=True)
            assert (root / "config.json").read_text() == original_config
        if failure == "none":
            # A completed marker skips all migration work on a later rollout.
            subprocess.run(["sh", "-ec", harness + doctor_setup + doctor, "fixture", directory, "doctor"],
                           check=True, capture_output=True)
print("OpenClaw doctor gate: backup, repair, preservation, and validation failures block completion")
