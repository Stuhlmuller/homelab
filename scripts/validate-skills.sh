#!/usr/bin/env bash
set -euo pipefail

SKILLS_DIR=".codex/skills"

if [[ ! -d "${SKILLS_DIR}" ]]; then
  echo "missing project skills directory: ${SKILLS_DIR}" >&2
  exit 1
fi

python3 - "${SKILLS_DIR}" <<'PY'
from pathlib import Path
import re
import sys

skills_dir = Path(sys.argv[1])
skill_files = sorted(skills_dir.glob("*/SKILL.md"))

if not skill_files:
    raise SystemExit(f"no skills found in {skills_dir}")

for skill_file in skill_files:
    content = skill_file.read_text()
    frontmatter_match = re.match(r"^---\n(.*?)\n---\n", content, re.S)
    if not frontmatter_match:
        raise SystemExit(f"{skill_file}: missing YAML frontmatter")

    metadata = {}
    for line in frontmatter_match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

    expected_name = skill_file.parent.name
    name = metadata.get("name")
    description = metadata.get("description")
    body = content[frontmatter_match.end():].strip()

    if not name:
        raise SystemExit(f"{skill_file}: missing skill name")
    if name != expected_name:
        raise SystemExit(
            f"{skill_file}: frontmatter name {name!r} does not match folder {expected_name!r}"
        )
    if not description:
        raise SystemExit(f"{skill_file}: missing skill description")
    if not body:
        raise SystemExit(f"{skill_file}: skill body is empty")

    print(f"validated skill: {name}")
PY
