#!/usr/bin/env python3
"""Exercise the installed Spec Kit CLIs without changing repository state."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


source = Path(__file__).resolve().parents[2] / ".specify"
for language, executable, suffix in [
    ("python", ["python3", "-B"], ".py"),
    ("bash", ["bash"], ".sh"),
]:
    with tempfile.TemporaryDirectory(prefix="speckit smoke ") as directory:
        root = Path(directory).resolve()
        shutil.copytree(source, root / ".specify")

        def run(name, *args):
            filename = (name.replace("-", "_") if language == "python" else name) + suffix
            result = subprocess.run(
                [*executable, str(root / ".specify/scripts" / language / filename), *args],
                cwd=root, text=True, capture_output=True, check=True,
            )
            return json.loads(result.stdout)

        preview = run("create-new-feature", "--json", "--dry-run", "the to an")
        assert preview["BRANCH_NAME"] == "001-the-to-an"
        assert preview["DRY_RUN"] and not (root / "specs").exists()
        feature = run("create-new-feature", "--json", "Verify Spec Kit setup")
        spec = Path(feature["SPEC_FILE"])
        assert spec.is_file()
        plan = run("setup-plan", "--json")
        plan_path = Path(plan["IMPL_PLAN"])
        assert plan_path.is_file()
        plan_path.write_text("# Existing plan\n")
        run("setup-plan", "--json")
        assert plan_path.read_text() == "# Existing plan\n"
        tasks = run("setup-tasks", "--json")
        assert Path(tasks["TASKS_TEMPLATE"]).is_file()
        (spec.parent / "tasks.md").write_text("# Tasks\n\n- [ ] T001 Smoke test\n")
        prerequisites = run("check-prerequisites", "--json", "--require-tasks", "--include-tasks")
        assert "tasks.md" in prerequisites["AVAILABLE_DOCS"]
        state = (root / ".specify/feature.json").read_bytes()
        paths = run("check-prerequisites", "--json", "--paths-only")
        assert Path(paths["FEATURE_DIR"]) == spec.parent
        assert (root / ".specify/feature.json").read_bytes() == state
        if language == "bash":
            result = subprocess.run(
                ["bash", "-c", 'source "$1"; format_speckit_command plan "$2"; get_repo_root',
                 "smoke", str(root / ".specify/scripts/bash/common.sh"), str(root)],
                cwd=root.parent, text=True, capture_output=True, check=True,
            )
            assert result.stdout.splitlines() == ["$speckit-plan", str(root)]
        print(f"Spec Kit {language}: feature creation, plans, tasks, and path resolution passed")
