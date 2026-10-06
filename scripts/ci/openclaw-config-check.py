#!/usr/bin/env python3
"""Exercise current bootstrap configuration and backup gates with private fixtures."""
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
gateway_version = subprocess.check_output(
    ["yq", "-r", '.controllers.openclaw.containers.app.image.tag', values], text=True,
).strip().split("@", 1)[0]
assert f"backup_name=pre-{gateway_version}" in bootstrap
# Execute the actual shell phase with a narrow CLI double. Native pinned-image
# tests own vendor validation semantics; these fixtures own our inputs/order.
phase = bootstrap[bootstrap.index('config_batch_dir="$(mktemp'):]
assert phase.count('openclaw config set ') == 1
assert 'openclaw config set --batch-file' in phase
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
elif args == ["assistant"]:
    assert "codex" not in state["plugins"].get("entries", {})
    assert state["plugins"]["entries"]["memory-wiki"]["enabled"] is True
    assert state["plugins"]["entries"]["openrouter"]["enabled"] is True
    assert state["plugins"]["allow"] == ["discord", "openrouter"]
    state["assistantPreserved"] = True
elif args not in (["config", "validate"], ["plugins", "enable", "discord", "--accept-capabilities"],
                  ["verify_discord_plugin", "loaded"]):
    raise AssertionError(args)
config.write_text(json.dumps(state))
'''
expected_events = ["batch:gateway.mode", "batch:hooks.enabled",
                   "batch:hooks.token", "batch:plugins.entries.memory-wiki.enabled",
                   "assistant",
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
original = {"hooks": {"token": "existing-hook-token", "unrelated": "retained"},
            "gateway": {"unrelated": ["retained"]}, "channels": {"discord": {"unrelated": True}},
            "agents": {"defaults": {"model": "fixture/model"}},
            "plugins": {"allow": ["discord", "openrouter"]},
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
                                       event.startswith("batch:hooks.")) or
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
            # A second bootstrap preserves the same managed and unrelated configuration.
            first = (root / "config.json").read_bytes()
            (root / "events").write_text("")
            result = subprocess.run(["sh", "-ec", harness + phase, "fixture", directory,
                                     sys.executable, hook, discord], capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            assert (root / "config.json").read_bytes() == first
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
    # A previous upgrade marker must not skip this release's archive.
    (state / ".backup-verified-for-previous-release").write_text("previous upgrade")
    backups = root / "openclaw-backups"
    staging = backups / ".pre-2026.9.5.partial"
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
    preserved = list(backups.glob("pre-2026.9.5.interrupted-*"))
    assert len(preserved) == 1
    assert (preserved[0] / "openclaw.tar.gz").read_bytes() == partial
    published = backups / "pre-2026.9.5/openclaw.tar.gz"
    archive_bytes = published.read_bytes()
    assert run_backup().returncode == 0
    assert published.read_bytes() == archive_bytes
    (state / ".backup-verified-for-2026.9.5").unlink()
    published.write_bytes(b"corrupt published backup")
    assert run_backup().returncode != 0
    assert published.read_bytes() == b"corrupt published backup"
print("OpenClaw backup gate: interrupted archive preserved, rebuild verified, corrupt published archive rejected")
