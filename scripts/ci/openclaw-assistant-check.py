#!/usr/bin/env python3
"""Check the actual assistant installer and scheduler without live credentials."""
import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

BUNDLE = Path("clusters/homelab/apps/openclaw/assistant")


def module(name):
    spec = importlib.util.spec_from_file_location(name, BUNDLE / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


bootstrap = module("bootstrap")
reconcile = module("reconcile")
fixture = {
    "agents": {"defaults": {"models": {"openai/gpt-5.5": {}},
                            "modelPolicy": {"allow": ["openai/gpt-5.5"]}}},
    "skills": {"allowBundled": ["existing-skill"]},
    "channels": {"discord": {"enabled": True, "allowFrom": ["123456789012345678"],
                             "token": {"source": "env", "provider": "default", "id": "TOKEN"}}},
}
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    config = root / "openclaw.json"
    config.write_text(json.dumps(fixture))
    workspace = root / "workspace"
    workspace.mkdir()
    soul = workspace / "SOUL.md"
    soul.write_text("Existing personal identity.\n")
    memory = workspace / "MEMORY.md"
    memory.write_text("Private memory must survive.\n")
    bootstrap.install(BUNDLE, root, config)
    result = json.loads(config.read_text())
    assert result["skills"] == fixture["skills"]
    assert result["channels"] == fixture["channels"]
    assert result["agents"]["defaults"]["modelPolicy"]["allow"] == [
        "openai/gpt-5.5", "openai/gpt-6-astra"]
    assert "Existing personal identity." in soul.read_text()
    assert memory.read_text() == "Private memory must survive.\n"
    assert (root / "assistant-backups/v1/SOUL.md").read_text() == "Existing personal identity.\n"
    snapshot = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    bootstrap.install(BUNDLE, root, config)
    assert snapshot == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert config.stat().st_mode & 0o777 == 0o600
    # Reject ambiguous or symlinked input before replacing existing workspace files.
    soul.write_text(bootstrap.START + bootstrap.START + bootstrap.END)
    before = config.read_bytes()
    try:
        bootstrap.install(BUNDLE, root, config)
        raise AssertionError("malformed section accepted")
    except ValueError:
        pass
    assert config.read_bytes() == before
    soul.unlink()
    soul.symlink_to(memory)
    try:
        bootstrap.install(BUNDLE, root, config)
        raise AssertionError("symlink accepted")
    except ValueError:
        pass
    assert memory.read_text() == "Private memory must survive.\n"

assert reconcile.owner_destination(fixture) == "user:123456789012345678"
for owners in ([], ["*"], ["123456789012345678", "987654321098765432"]):
    config = copy.deepcopy(fixture)
    config["channels"]["discord"]["allowFrom"] = owners
    try:
        reconcile.owner_destination(config)
        raise AssertionError("unresolved/ambiguous owner accepted")
    except ValueError:
        pass
jobs = json.loads((BUNDLE / "jobs.json").read_text())
keys = set()
for job in jobs:
    argv = reconcile.command(job, "user:123456789012345678")
    key = argv[argv.index("--declaration-key") + 1]
    assert key not in keys
    keys.add(key)
    assert argv[argv.index("--channel") + 1] == "discord"
    assert "--disabled" not in argv  # Let declarative reconciliation preserve pauses.
    assert "--best-effort-deliver" not in argv  # Delivery failure must remain visible.
    assert argv[argv.index("--model") + 1] == "openai/gpt-6-astra"

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    reconcile.CONFIG = root / "config.json"
    reconcile.STATUS = root / "status.json"
    reconcile.BUNDLE = BUNDLE
    for config in ({}, {"channels": {"discord": {"enabled": False}}}):
        reconcile.CONFIG.write_text(json.dumps(config))
        with patch.object(reconcile.subprocess, "run") as run:
            reconcile.reconcile()
            run.assert_not_called()
        assert json.loads(reconcile.STATUS.read_text())["state"] == "deferred"
    reconcile.CONFIG.write_text(json.dumps(fixture))
    with patch.object(reconcile.subprocess, "run") as run:
        run.return_value.returncode = 0
        reconcile.reconcile()
        assert run.call_count == 3
    assert json.loads(reconcile.STATUS.read_text())["state"] == "ready"
    with patch.object(reconcile.subprocess, "run") as run, patch.object(reconcile.time, "sleep"):
        run.return_value.returncode = 1
        reconcile.reconcile()
        assert run.call_count == 6
    assert json.loads(reconcile.STATUS.read_text())["state"] == "failed"
    assert reconcile.STATUS.stat().st_mode & 0o777 == 0o600

digest = hashlib.sha256()
for path in sorted(BUNDLE.iterdir()):
    if path.is_file():
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
values = Path("clusters/homelab/apps/openclaw/values.yaml").read_text()
assert f'homelab.rst.io/openclaw-assistant-sha256: "{digest.hexdigest()}"' in values
print("OpenClaw assistant: preservation, idempotence, routing, schedules, rollout checksum passed")
