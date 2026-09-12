#!/usr/bin/env python3
"""Report only a fixed stage label from an otherwise private plan log."""

import sys

STAGES = (
    "kubeconfig", "api-readiness", "filter", "stack-generation",
    "bootstrap-plan", "bootstrap-json", "application-plans", "application-json",
    "deleted-units", "azure-plan", "azure-json", "policy",
)
MARKERS = {f"homelab-plan-stage: {stage}".encode(): stage for stage in STAGES}


def last_stage(lines):
    stage = "nix-setup"
    for line in lines:
        stage = MARKERS.get(line.removesuffix(b"\n"), stage)
    return stage


def main(arguments):
    stage = "unavailable"
    if len(arguments) == 1:
        try:
            with open(arguments[0], "rb") as log:
                stage = last_stage(log)
        except (OSError, ValueError):
            # File errors can include private paths; emit the fixed label only.
            pass
    print(f"::error::Live plan failed; last entered stage: {stage}. "
          "Detailed output withheld because this is a public repository.")


if __name__ == "__main__":
    main(sys.argv[1:])
