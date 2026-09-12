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

# Execute the actual shell phase with a narrow CLI double. Native pinned-image
# tests own vendor validation semantics; these fixtures own our inputs/order.
phase = bootstrap[bootstrap.index('config_batch_dir="$(mktemp'):bootstrap.rindex('if [ ! -s "$doctor_marker" ]; then')]
assert phase.count('openclaw config set ') == 1
assert 'openclaw config set --batch-file' in phase
assert bootstrap.index('session_preservation verify') < bootstrap.index(phase)
assert bootstrap.index(phase) < bootstrap.rindex('if [ ! -s "$doctor_marker" ]; then')
mock = r'''
import json, os, pathlib, sys
root = pathlib.Path(sys.argv[1])
args = sys.argv[2:]
config = root / "config.json"
state = json.loads(config.read_text())
entries = None
if args[:3] == ["config", "set", "--batch-file"]:
    assert len(args) == 4
    path = pathlib.Path(args[3])
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    entries = json.loads(path.read_text())
    event = "batch:" + entries[0]["path"]
    with (root / "paths").open("a") as output:
        output.write(str(path.parent) + "\n")
else:
    event = " ".join(args)
with (root / "events").open("a") as output:
    output.write(event + "\n")
if event == (root / "failure").read_text():
    sys.exit(23)
if entries:
    # Apply targeted edits, preserving all other fields. No simulated validation.
    for entry in entries:
        assert set(entry) in ({"path", "value"}, {"path", "ref"})
        target = state
        parts = entry["path"].split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = entry.get("ref", entry.get("value"))
elif args == ["config", "unset", "hooks.token"]:
    del state["hooks"]["token"]
elif args == ["assistant"]:
    assert state["plugins"]["entries"]["codex"]["enabled"] is True
    assert state["plugins"]["entries"]["memory-wiki"]["enabled"] is True
    state["assistantPreserved"] = True
elif args not in (["config", "validate"], ["plugins", "enable", "discord", "--accept-capabilities"],
                  ["verify_discord_plugin", "loaded"]):
    raise AssertionError(args)
config.write_text(json.dumps(state))
'''
expected_events = ["batch:gateway.mode", "batch:hooks.enabled", "config unset hooks.token",
                   "batch:hooks.token", "batch:plugins.entries.codex.enabled", "assistant",
                   "config validate", "batch:agents.defaults.sandbox.mode",
                   "plugins enable discord --accept-capabilities", "verify_discord_plugin loaded",
                   "batch:channels.discord.enabled"]
harness = r'''OPENCLAW_CONFIG_PATH="$1/config.json"
fixture_root="$1"
fixture_python="$2"
GRAFANA_ALERT_HOOK_TOKEN="$3"
DISCORD_BOT_TOKEN="$4"
export GRAFANA_ALERT_HOOK_TOKEN DISCORD_BOT_TOKEN
openclaw() { "$fixture_python" "$fixture_root/mock.py" "$fixture_root" "$@"; }
python3() {
  if [ "$1" = /etc/openclaw-assistant/bootstrap.py ]; then
    openclaw assistant
  else
    "$fixture_python" "$@"
  fi
}
verify_discord_plugin() { openclaw verify_discord_plugin "$@"; }
'''
original = {"hooks": {"token": "${GRAFANA_ALERT_HOOK_TOKEN}", "unrelated": "retained"},
            "gateway": {"unrelated": ["retained"]}, "channels": {"discord": {"unrelated": True}},
            "agents": {"defaults": {"model": "fixture/model"}},
            "skills": {"allowBundled": ["fixture"]}}
# Both conditionals are independent; weird characters remain data, not shell code.
credential = 'fixture-"quote"\n$(exit 99)`exit 99`\\token'
for hook, discord in (("", ""), ("REPLACE_ME", "REPLACE_ME"), (credential, ""),
                      ("", "fixture-discord"), (credential, "fixture-discord")):
    failures = [""] + (expected_events if hook == credential and discord == "fixture-discord" else [])
    for failure in failures:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "mock.py").write_text(mock)
            (root / "config.json").write_text(json.dumps(original))
            (root / "failure").write_text(failure)
            result = subprocess.run(["sh", "-ec", harness + phase, "fixture", directory,
                                     sys.executable, hook, discord], capture_output=True, text=True)
            events = (root / "events").read_text().splitlines()
            paths = (root / "paths").read_text().splitlines()
            assert all(not pathlib.Path(path).exists() for path in paths)
            assert credential not in result.stdout + result.stderr
            if failure:
                assert result.returncode != 0, failure
                assert events == expected_events[:expected_events.index(failure) + 1], events
                continue
            assert result.returncode == 0, result.stderr
            expected_order = [event for event in expected_events
                              if not ((hook in ("", "REPLACE_ME") and
                                       (event.startswith("batch:hooks.") or event == "config unset hooks.token")) or
                                      (discord in ("", "REPLACE_ME") and
                                       (event.startswith("plugins enable discord") or
                                        event.startswith("verify_discord_plugin") or
                                        event == "batch:channels.discord.enabled")))]
            assert events == expected_order, events
            assert sum(event.startswith("batch:") for event in events) == (
                3 + 2 * (hook not in ("", "REPLACE_ME")) + (discord not in ("", "REPLACE_ME")))
            state = json.loads((root / "config.json").read_text())
            assert state["gateway"]["unrelated"] == ["retained"]
            assert state["hooks"]["unrelated"] == "retained"
            assert state["agents"]["defaults"]["model"] == "fixture/model"
            assert state["skills"] == original["skills"]
            assert state["channels"]["discord"]["unrelated"] is True
            assert state["gateway"]["auth"]["token"] == {
                "source": "env", "provider": "default", "id": "OPENCLAW_GATEWAY_TOKEN"}
            if hook not in ("", "REPLACE_ME"):
                assert state["hooks"]["token"] == hook
                assert state["hooks"]["allowRequestSessionKey"] is False
                assert state["hooks"]["allowedAgentIds"] == ["main"]
            else:
                assert state["hooks"] == original["hooks"]
            if discord not in ("", "REPLACE_ME"):
                assert state["channels"]["discord"]["token"] == {
                    "source": "env", "provider": "default", "id": "DISCORD_BOT_TOKEN"}
            else:
                assert state["channels"] == original["channels"]
            # A second bootstrap preserves config and skips the legacy token unset.
            first = (root / "config.json").read_bytes()
            (root / "events").write_text("")
            result = subprocess.run(["sh", "-ec", harness + phase, "fixture", directory,
                                     sys.executable, hook, discord], capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            assert (root / "config.json").read_bytes() == first
            assert "config unset hooks.token" not in (root / "events").read_text()
            assert all(not pathlib.Path(path).exists() for path in (root / "paths").read_text().splitlines())
print("OpenClaw batch bootstrap: 3–6 CLI writes; conditional/order/preservation/idempotence/failure cleanup passed")

batch_setup = phase.split("config_batch <<'OPENCLAW_GATEWAY_BATCH'", 1)[0]
for payload in (b'{"not": "a list"}', b'{"broken":', b' ' * 1048577):
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        script = '''fixture_root="$1"
mktemp() {
  created="$(command mktemp "$@")"
  printf '%s' "$created" > "$fixture_root/created"
  printf '%s\\n' "$created"
}
openclaw() { touch "$fixture_root/cli-called"; }
''' + batch_setup + '\nconfig_batch\n'
        result = subprocess.run(["sh", "-ec", script, "fixture", directory],
                                input=payload, capture_output=True)
        assert result.returncode != 0
        assert not (root / "cli-called").exists()
        assert not pathlib.Path((root / "created").read_text()).exists()
print("OpenClaw batch input: malformed, wrong-shape, and oversized inputs rejected before CLI; cleaned")

# Exercise the complete backup gate with a genuinely truncated archive.
backup_gate = bootstrap[bootstrap.index('backup_root='):bootstrap.index('mkdir -p "$OPENCLAW_STATE_DIR" "$OPENCLAW_WORKSPACE_DIR"')]
with tempfile.TemporaryDirectory() as directory:
    root = pathlib.Path(directory)
    state = root / "openclaw"
    (state / "state").mkdir(parents=True)
    (state / "agents/main/agent").mkdir(parents=True)
    (state / "state/history").write_text("canonical history")
    backups = root / "openclaw-backups"
    staging = backups / ".pre-2026.9.2.partial"
    staging.mkdir(parents=True)
    partial = b"truncated gzip fixture"
    (staging / "openclaw.tar.gz").write_bytes(partial)
    gate = backup_gate.replace("backup_root=/data/openclaw-backups", 'backup_root="$fixture/openclaw-backups"')
    gate = gate.replace("-C /data", '-C "$fixture"').replace("df -Pk /data", 'df -Pk "$fixture"')
    harness = 'fixture="$1"\nOPENCLAW_STATE_DIR="$1/openclaw"\nhad_existing_state=true\n'
    def run_backup():
        return subprocess.run(["sh", "-ec", harness + gate, "fixture", directory], capture_output=True)
    result = run_backup()
    assert result.returncode == 0, result.stderr
    preserved = list(backups.glob("pre-2026.9.2.interrupted-*"))
    assert len(preserved) == 1
    assert (preserved[0] / "openclaw.tar.gz").read_bytes() == partial
    published = backups / "pre-2026.9.2/openclaw.tar.gz"
    archive_bytes = published.read_bytes()
    assert run_backup().returncode == 0
    assert published.read_bytes() == archive_bytes
    (state / ".backup-verified-for-2026.9.2").unlink()
    published.write_bytes(b"corrupt published backup")
    assert run_backup().returncode != 0
    assert published.read_bytes() == b"corrupt published backup"
print("OpenClaw backup gate: interrupted archive preserved, rebuild verified, corrupt published archive rejected")
