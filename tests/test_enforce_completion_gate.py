import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/ci/enforce_completion_gate.py"

CHECKLIST_BODY = "\n".join(
    [
        "- [x] I ran repository validation (`make validate`) after my final code edits.",
        "- [x] I committed and pushed the final implementation changes for this issue.",
        "- [x] I understand this work is only complete after this PR is merged into `main`.",
    ]
)


def _run(event_payload: dict) -> subprocess.CompletedProcess[str]:
    event_path = ROOT / ".codex-tmp" / "completion-gate-event.json"
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event_path.write_text(json.dumps(event_payload), encoding="utf-8")

    env = dict(os.environ)
    env["GITHUB_EVENT_NAME"] = "pull_request"
    env["GITHUB_EVENT_PATH"] = str(event_path)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_renovate_pr_skips_completion_gate() -> None:
    proc = _run(
        {
            "pull_request": {
                "title": "chore(deps): update aws-actions/configure-aws-credentials digest to d979d5b",
                "body": "",
                "user": {"login": "rstuhlmuller-renovate[bot]"},
            }
        }
    )
    assert proc.returncode == 0
    assert "completion gate skipped: dependency bot pull request" in proc.stdout


def test_human_pr_requires_checklist_items() -> None:
    proc = _run(
        {
            "pull_request": {
                "title": "Improve CI diagnostics",
                "body": "",
                "user": {"login": "engineer1"},
                "labels": [{"name": "qa-approved"}],
            }
        }
    )
    assert proc.returncode == 1
    assert "completion gate failed" in proc.stdout
    assert "missing checked checklist items:" in proc.stdout


def test_human_pr_requires_qa_approved_label() -> None:
    proc = _run(
        {
            "pull_request": {
                "title": "Improve CI diagnostics",
                "body": CHECKLIST_BODY,
                "user": {"login": "engineer1"},
                "labels": [{"name": "documentation"}],
            }
        }
    )
    assert proc.returncode == 1
    assert "missing required pull request label: qa-approved" in proc.stdout


def test_human_pr_passes_with_checklist_and_label() -> None:
    proc = _run(
        {
            "pull_request": {
                "title": "Improve CI diagnostics",
                "body": CHECKLIST_BODY,
                "user": {"login": "engineer1"},
                "labels": [{"name": "qa-approved"}],
            }
        }
    )
    assert proc.returncode == 0
    assert "completion gate passed" in proc.stdout
