#!/usr/bin/env python3
"""Prepare and validate a private NRI candidate; never contact or mutate a node."""

import argparse
import copy
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NRI_FILE = "/etc/cri/conf.d/20-network-policy-nri.part"


def run(*args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError("Offline Talos NRI preparation command failed; private output was withheld")
    return result.stdout


def documents(path):
    return json.loads(run("yq", "ea", "-o=json", "-I=0", "[.]", str(path)))


def desired(original, declaration):
    configs = [item for item in original if item.get("version") == "v1alpha1"]
    if len(configs) != 1:
        raise ValueError("Expected exactly one v1alpha1 machine configuration")
    wanted = declaration["machine"]["files"]
    if len(wanted) != 1 or wanted[0]["path"] != NRI_FILE:
        raise ValueError("NRI declaration must contain only its owned CRI fragment")
    result = copy.deepcopy(original)
    config = next(item for item in result if item.get("version") == "v1alpha1")
    files = config["machine"].get("files", [])
    existing = [item for item in files if item["path"] == NRI_FILE]
    if len(existing) > 1:
        raise ValueError("Duplicate NRI declarations must be reconciled before rollout")
    wanted = copy.deepcopy(wanted)
    if existing:
        wanted[0]["op"] = "overwrite"
    config["machine"]["files"] = [item for item in files if item["path"] != NRI_FILE] + wanted
    return result


def prepare(source, output, rollback=False, talosctl="talosctl"):
    if output.is_symlink():
        raise ValueError("Use a new private output file outside the checkout")
    output = output.expanduser().resolve()
    if output.is_relative_to(ROOT) or output.exists():
        raise ValueError("Use a new private output file outside the checkout")
    patch = ROOT / (".talos/patches/network-policy-nri-rollback.yaml" if rollback else ".talos/patches/network-policy-nri.yaml")
    candidate = desired(documents(source), documents(patch)[0])
    serialized = "---\n".join(run("yq", "-p=json", "-o=yaml", ".", "-", input=json.dumps(doc)) for doc in candidate)
    with tempfile.TemporaryDirectory(prefix="talos-nri-candidate-") as directory:
        private = Path(directory) / "candidate.yaml"
        private.write_text(serialized)
        private.chmod(0o600)
        run(talosctl, "validate", "--config", str(private), "--mode", "metal", "--strict")
        assert documents(private) == candidate, "Candidate serialization changed configuration"
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(serialized)
    print("NRI candidate validated; no node contacted or changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--talosctl", default="talosctl")
    args = parser.parse_args()
    prepare(args.input, args.output, args.rollback, args.talosctl)


if __name__ == "__main__":
    main()
