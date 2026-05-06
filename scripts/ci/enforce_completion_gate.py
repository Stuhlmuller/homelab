#!/usr/bin/env python3
"""Fail PR checks until completion checklist items and QA label are present."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


REQUIRED_AUTHOR_ITEMS = (
    "I ran repository validation (`make validate`) after my final code edits.",
    "I committed and pushed the final implementation changes for this issue.",
    "I understand this work is only complete after this PR is merged into `main`.",
)
REQUIRED_LABEL = "qa-approved"
DEPENDENCY_BOT_MARKERS = ("renovate[bot]", "dependabot[bot]")


def _extract_checked_items(body: str) -> set[str]:
    pattern = re.compile(r"^\s*-\s*\[[xX]\]\s*(.+?)\s*$", re.MULTILINE)
    return {match.group(1).strip() for match in pattern.finditer(body)}


def _should_skip_for_dependency_bot(pull_request: dict) -> bool:
    user_login = str((pull_request.get("user") or {}).get("login") or "").lower()
    title = str(pull_request.get("title") or "").lower()
    if any(marker in user_login for marker in DEPENDENCY_BOT_MARKERS):
        return True
    return title.startswith("chore(deps):")


def _has_required_label(pull_request: dict) -> bool:
    labels = pull_request.get("labels") or []
    label_names = {
        str(label.get("name") or "").strip().lower()
        for label in labels
        if isinstance(label, dict)
    }
    return REQUIRED_LABEL.lower() in label_names


def main() -> int:
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    if event_name != "pull_request" or not event_path:
        print("completion gate skipped: not a pull_request event")
        return 0

    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pull_request = payload.get("pull_request") or {}

    if _should_skip_for_dependency_bot(pull_request):
        print("completion gate skipped: dependency bot pull request")
        return 0

    body = str(pull_request.get("body") or "")
    checked_items = _extract_checked_items(body)

    missing_items = [item for item in REQUIRED_AUTHOR_ITEMS if item not in checked_items]
    missing_required_label = not _has_required_label(pull_request)

    if not missing_items and not missing_required_label:
        print("completion gate passed")
        return 0

    print("completion gate failed")
    if missing_items:
        print("missing checked checklist items:")
        for item in missing_items:
            print(f"- {item}")
    if missing_required_label:
        print(f"missing required pull request label: {REQUIRED_LABEL}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
