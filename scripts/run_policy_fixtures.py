#!/usr/bin/env python3
"""Run restore policy guardrail fixtures and enforce expected outcomes."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARDRAIL_SCRIPT = ROOT / "scripts" / "preflight_policy_guardrails.py"
FIXTURE_ROOT = ROOT / "fixtures" / "policy"


def run_fixture(path: Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["python3", str(GUARDRAIL_SCRIPT), "--request", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode, output


def main() -> int:
    failures: list[str] = []

    for path in sorted((FIXTURE_ROOT / "pass").glob("*.json")):
        code, output = run_fixture(path)
        if code != 0:
            failures.append(f"expected PASS for {path.name}, got code {code}: {output}")

    for path in sorted((FIXTURE_ROOT / "fail").glob("*.json")):
        code, output = run_fixture(path)
        if code == 0:
            failures.append(f"expected FAIL for {path.name}, got pass output: {output}")

    if failures:
        print("Policy fixture failures:")
        for item in failures:
            print(f"- {item}")
        return 1

    print("All restore policy fixtures matched expected outcomes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
