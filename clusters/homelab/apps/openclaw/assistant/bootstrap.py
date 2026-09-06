#!/usr/bin/env python3
"""Install repository-owned assistant sections while the gateway is stopped."""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

START = "<!-- homelab-assistant:managed:start -->"
END = "<!-- homelab-assistant:managed:end -->"
FILES = ("SOUL.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md")


def merge(current, patch):
    for key, value in patch.items():
        if isinstance(value, dict):
            if not isinstance(current.get(key), dict):
                current[key] = {}
            merge(current[key], value)
        else:
            current[key] = value


def section(original, managed):
    if START in original or END in original:
        if original.count(START) != 1 or original.count(END) != 1:
            raise ValueError("ambiguous managed section; preserve original and stop")
        before, rest = original.split(START)
        _, after = rest.split(END)
        original = (before + after).strip()
    block = f"{START}\n{managed.strip()}\n{END}\n"
    return block + ("\n" + original.strip() + "\n" if original.strip() else "")


def atomic_write(path, content):
    if path.is_symlink():
        raise ValueError("refusing to replace a symlink")
    data = content.encode()
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".assistant-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def install(bundle, state, config_path):
    config = json.loads(config_path.read_text())
    defaults = config.setdefault("agents", {}).setdefault("defaults", {})
    main = config["agents"].get("entries", {}).get("main", {})
    workspace = Path(main.get("workspace", defaults.get("workspace", state / "workspace")))
    if not workspace.is_absolute() or not workspace.resolve().is_relative_to(state.resolve()):
        raise ValueError("main workspace must be inside persistent OpenClaw state")
    patch = json.loads((bundle / "config.json").read_text())
    model = patch["agents"]["defaults"]["model"]["primary"]
    # A migrated allowlist must include Astra; an empty list means unrestricted.
    allowed = defaults.get("modelPolicy", {}).get("allow")
    if allowed and model not in allowed:
        allowed.append(model)
    if "model" in main:
        main["model"] = patch["agents"]["defaults"]["model"]
    if "heartbeat" in main:
        main["heartbeat"] = patch["agents"]["defaults"]["heartbeat"]
    existing_tools = config.get("tools", {}).get("alsoAllow", [])
    patch["tools"]["alsoAllow"] = list(dict.fromkeys(existing_tools + patch["tools"]["alsoAllow"]))
    merge(config, patch)
    updates = []
    for name in FILES:
        path = workspace / name
        if path.is_symlink():
            raise ValueError("managed workspace files must not be symlinks")
        original = path.read_text() if path.exists() else ""
        # Retire the old polling checklist, which otherwise duplicates managed jobs.
        retained = "" if name == "HEARTBEAT.md" else original
        updates.append((path, original, section(retained, (bundle / name).read_text())))
    # Validate every section before making any change; retain the first originals.
    backup = state / "assistant-backups" / "v1"
    first_install = not (backup / "openclaw.json").exists()
    for path, original, updated in updates:
        saved = backup / path.name
        if first_install and path.exists() and not saved.exists():
            atomic_write(saved, original)
        atomic_write(path, updated)
    saved_config = backup / "openclaw.json"
    if not saved_config.exists():
        atomic_write(saved_config, config_path.read_text())
    atomic_write(config_path, json.dumps(config, indent=2) + "\n")
    digest = hashlib.sha256((bundle / "config.json").read_bytes()).hexdigest()
    print(f"Assistant workspace sections and model configured ({digest[:12]})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=Path("/etc/openclaw-assistant"))
    parser.add_argument("--state", type=Path, default=Path("/data/openclaw"))
    parser.add_argument("--config", type=Path, default=Path("/data/openclaw/config/openclaw.json"))
    args = parser.parse_args()
    install(args.bundle, args.state, args.config)
