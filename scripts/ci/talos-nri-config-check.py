#!/usr/bin/env python3
"""Validate only the committed NRI file mutation against generated Talos configs."""

import copy
import json
import importlib.util
import subprocess
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NRI_FILE = "/etc/cri/conf.d/20-network-policy-nri.part"
spec = importlib.util.spec_from_file_location("nri", ROOT / "scripts/talos-nri-config.py")
nri_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nri_module)


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Offline Talos validation command failed; private output withheld")
    return result.stdout


def load(path):
    return json.loads(run("yq", "ea", "-o=json", "-I=0", "[.]", str(path)))


def check():
    with tempfile.TemporaryDirectory(prefix="talos-nri-check-") as directory:
        root = Path(directory)
        run("talosctl", "gen", "config", "nri-validation", "https://192.0.2.1:6443",
            "--with-docs=false", "--with-examples=false", "--output-dir", directory)
        for kind in ("worker", "controlplane"):
            baseline = root / (kind + ".yaml")
            sentinel = {"path": "/etc/cri/conf.d/10-existing.part", "op": "create", "permissions": 420,
                        "content": '[plugins."io.containerd.cri.v1.images"]\n  stats_collect_period = 10\n'}
            seeded = root / (kind + "-seeded.yaml")
            run("talosctl", "machineconfig", "patch", str(baseline), "--patch",
                json.dumps({"machine": {"files": [sentinel]}}), "--output", str(seeded))
            baseline = seeded
            original = load(baseline)
            enabled = root / (kind + "-enabled.yaml")
            nri_module.prepare(baseline, enabled)
            assert enabled.stat().st_mode & 0o777 == 0o600
            for unsafe in (enabled, ROOT / "must-not-write-nri.yaml"):
                try:
                    nri_module.prepare(baseline, unsafe)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Unsafe private output destination accepted")
            rolled_back = root / (kind + "-rollback.yaml")
            for mode, path, disabled in (("enabled", enabled, False), ("rollback", rolled_back, True),
                                         ("re-enabled", root / (kind + "-re-enabled.yaml"), False)):
                if mode == "rollback":
                    nri_module.prepare(enabled, path, rollback=True)
                elif mode == "re-enabled":
                    nri_module.prepare(rolled_back, path)
                run("talosctl", "validate", "--config", str(path), "--mode", "metal", "--strict")
                docs = load(path)
                files = docs[0]["machine"]["files"]
                nri = [item for item in files if item["path"] == NRI_FILE]
                assert len(nri) == 1
                plugin = tomllib.loads(nri[0]["content"])["plugins"]["io.containerd.nri.v1.nri"]
                assert plugin == {"disable": disabled, "socket_path": "/var/run/nri/nri.sock"}
                assert nri[0]["permissions"] == 420
                assert nri[0]["op"] == ("create" if mode == "enabled" else "overwrite")
                normalized = copy.deepcopy(docs)
                normalized[0]["machine"]["files"] = [item for item in files if item["path"] != NRI_FILE]
                assert normalized == original, "NRI mutation changed unrelated machine configuration"
            duplicate = copy.deepcopy(load(enabled))
            duplicate[0]["machine"]["files"].append(copy.deepcopy(duplicate[0]["machine"]["files"][-1]))
            try:
                nri_module.desired(duplicate, nri_module.documents(ROOT / ".talos/patches/network-policy-nri.yaml")[0])
            except ValueError:
                pass
            else:
                raise AssertionError("Duplicate NRI entries passed preparation")
        print("Talos NRI enable/rollback/re-enable valid; private output and unrelated configuration preserved")


if __name__ == "__main__":
    check()
