#!/usr/bin/env python3
"""Verify private merged CRI snapshots contain only the declared NRI change."""

import argparse
import copy
import importlib.util
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = "io.containerd.nri.v1.nri"
spec = importlib.util.spec_from_file_location("nri", ROOT / "scripts/talos-nri-config.py")
nri = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nri)


def verify(before, after, rollback=False):
    patch = ROOT / (".talos/patches/network-policy-nri-rollback.yaml" if rollback
                    else ".talos/patches/network-policy-nri.yaml")
    declaration = nri.documents(patch)[0]["machine"]["files"][0]
    wanted = tomllib.loads(declaration["content"])["plugins"][PLUGIN]
    expected = copy.deepcopy(before)
    expected.setdefault("plugins", {}).setdefault(PLUGIN, {}).update(wanted)
    actual = after.get("plugins", {}).get(PLUGIN, {})
    if (type(actual.get("disable")) is not bool or after != expected):
        raise ValueError("Effective CRI configuration differs from the declared NRI change; private values withheld")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    try:
        before = tomllib.loads(args.before.read_text())
        after = tomllib.loads(args.after.read_text())
        verify(before, after, args.rollback)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise SystemExit("Effective NRI verification failed; private configuration withheld") from None
    print("Effective NRI state matches declaration; unrelated CRI settings preserved; no live mutation")


if __name__ == "__main__":
    main()
