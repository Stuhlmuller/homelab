#!/usr/bin/env python3
"""Exercise the installed Spec Kit CLIs without changing repository state."""

import json
import os
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
        shutil.copytree(source, root / ".specify", ignore=shutil.ignore_patterns("feature.json", "__pycache__"))
        (root / "stale-project/.specify").mkdir(parents=True)
        # Regression fixture: inherited shell state must never select a feature.
        stale_environment = dict(os.environ, SPECIFY_INIT_DIR=str(root / "stale-project"),
                                 SPECIFY_FEATURE_DIRECTORY=str(root / "stale-feature"),
                                 SPECIFY_FEATURE="stale-feature")

        def run(name, *args, expected=0):
            filename = (name.replace("-", "_") if language == "python" else name) + suffix
            result = subprocess.run(
                [*executable, str(root / ".specify/scripts" / language / filename), *args],
                cwd=root, env=stale_environment, text=True, capture_output=True,
            )
            assert result.returncode == expected, result.stderr
            assert "export SPECIFY_" not in result.stdout + result.stderr
            if expected:
                return None
            return json.loads(result.stdout)

        run("check-prerequisites", "--json", "--paths-only", expected=1)
        assert not (root / ".specify/feature.json").exists()
        preview = run("create-new-feature", "--json", "--dry-run", "the to an")
        assert preview["BRANCH_NAME"] == "001-the-to-an"
        assert preview["DRY_RUN"] and not (root / "specs").exists()
        feature = run("create-new-feature", "--json", "Verify Spec Kit setup")
        spec = Path(feature["SPEC_FILE"])
        assert spec.is_file()
        assert spec.parent.parent == root / "specs"
        state = (root / ".specify/feature.json").read_bytes()
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
        paths = run("check-prerequisites", "--json", "--paths-only")
        assert Path(paths["FEATURE_DIR"]) == spec.parent
        assert paths["BRANCH"] == spec.parent.name
        assert (root / ".specify/feature.json").read_bytes() == state
        assert not (root / "stale-feature").exists()
        (root / ".specify/feature.json").write_text('{"feature_directory": ""}')
        run("check-prerequisites", "--json", "--paths-only", expected=1)
        if language == "bash":
            result = subprocess.run(
                ["bash", "-c", 'source "$1"; format_speckit_command plan "$2"; get_repo_root',
                 "smoke", str(root / ".specify/scripts/bash/common.sh"), str(root)],
                cwd=root.parent, env=stale_environment, text=True, capture_output=True, check=True,
            )
            assert result.stdout.splitlines() == ["$speckit-plan", str(root)]
        print(f"Spec Kit {language}: feature creation, plans, tasks, and path resolution passed")
