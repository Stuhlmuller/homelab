#!/usr/bin/env python3
"""Validate the unapplied NRI containerd fragment without live access."""

import json
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / ".talos/patches/nri-containerd.yaml"
NRI_FILE = "/etc/cri/conf.d/30-nri.part"


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        stderr = re.sub(r"[A-Za-z0-9+/=_-]{48,}", "[redacted]", result.stderr.strip())
        stderr = re.sub(r"(?i)\b((?:secret|token|password|privatekey)\s*[:=]\s*)\S+",
                        r"\1[redacted]", stderr)
        command = " ".join(map(str, args[:3]))
        raise RuntimeError(f"{command} failed (exit {result.returncode}): "
                           f"{stderr or 'no stderr'}; generated configuration withheld")
    return result.stdout


def check():
    if any(NRI_FILE in path.read_text() for path in (ROOT / ".talos/patches").glob("*.yaml")
           if path != PATCH):
        raise ValueError("NRI customization path already has an owner")
    with tempfile.TemporaryDirectory(prefix="talos-nri-preparation-") as directory:
        output = Path(directory)
        run("talosctl", "gen", "config", "nri-preparation", "https://192.0.2.1:6443",
            "--with-docs=false", "--with-examples=false", "--output-dir", directory)
        declaration = json.loads(run("yq", "-o=json", ".", str(PATCH)))
        files = declaration.get("machine", {}).get("files")
        if not isinstance(files, list) or len(files) != 1:
            raise ValueError("NRI declaration must own exactly one file")
        fragment = files[0]
        expected = {"plugins": {"io.containerd.nri.v1.nri": {"disable": False}}}
        if (not isinstance(fragment, dict) or set(fragment) != {"path", "op", "permissions", "content"}
                or fragment["path"] != NRI_FILE or fragment["op"] != "create"
                or fragment["permissions"] != 0o644 or tomllib.loads(fragment["content"]) != expected):
            raise ValueError("NRI declaration differs from the reviewed containerd override")
        candidate = output / (PATCH.stem + ".yaml")
        run("talosctl", "machineconfig", "patch", output / "worker.yaml",
            "--patch", "@" + str(PATCH), "--output", candidate)
        run("talosctl", "validate", "--config", candidate, "--mode", "metal", "--strict")
        rendered_paths = run("yq", "-r", f'.machine.files[]? | select(.path == "{NRI_FILE}") | .path',
                             str(candidate)).splitlines()
        if rendered_paths != [NRI_FILE]:
            raise ValueError("NRI declaration did not render as one isolated file")
    print("Talos NRI preparation fragment is strict-valid; no node contacted or changed")


if __name__ == "__main__":
    check()
