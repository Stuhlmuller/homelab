#!/usr/bin/env python3
"""Run the SC-001 evaluator from its GitOps-mounted canonical source."""

import importlib.util
from pathlib import Path
import sys


SOURCE = (Path(__file__).resolve().parents[1] / "clusters/homelab/apps/renovate"
          / "renovate-acceptance-schedule.py")
SPEC = importlib.util.spec_from_file_location("renovate_schedule", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def __getattr__(name):
    return getattr(MODULE, name)


if __name__ == "__main__":
    sys.exit(MODULE.main())
