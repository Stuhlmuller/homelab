#!/usr/bin/env python3
"""Fail PR checks until author-controlled completion checklist items are checked."""

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
def _extract_checked_items(body: str) -> set[str]:
    pattern = re.compile(r"^\s*-\s*\[[xX]\]\s*(.+?)\s*$", re.MULTILINE)
    return {match.group(1).strip() for match in pattern.finditer(body)}


def main() -> int:
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    if event_name != "pull_request" or not event_path:
        print("completion gate skipped: not a pull_request event")
        return 0

    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pull_request = payload.get("pull_request") or {}
    body = str(pull_request.get("body") or "")
    checked_items = _extract_checked_items(body)

    missing_items = [item for item in REQUIRED_AUTHOR_ITEMS if item not in checked_items]
    if not missing_items:
        print("completion gate passed")
        return 0

    print("completion gate failed")
    if missing_items:
        print("missing checked checklist items:")
        for item in missing_items:
            print(f"- {item}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
