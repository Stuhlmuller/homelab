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
