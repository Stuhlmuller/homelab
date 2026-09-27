#!/usr/bin/env python3
"""Publish the Octelium-protected Multica Service to localhost."""
import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import importlib.util
import pathlib
import re
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("native", ROOT / "scripts/octelium-nofx-reconcile.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def verified_client():
    executable = shutil.which("octelium")
    if not executable:
        raise RuntimeError("Install the pinned CLI with scripts/install-octeliumctl.sh")
    version = subprocess.run(
        [executable, "version"], capture_output=True, text=True, timeout=15, check=True,
    ).stdout
    expected = {"releaseVersion": "v0.35.0", "gitCommit": "5e4eb3e36911ba4f66f5f43df2cc4b264211c4ce"}
    fields = dict(re.findall(r"^([A-Za-z]+):\s*(\S+)\s*$", version, re.MULTILINE))
    if any(fields.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Octelium CLI must match the pinned release and source commit")
    return executable


def connect_command(client):
    return [
        client, "connect", "--domain", "stinkyboi.com", "--implementation", "gvisor",
        "--no-dns", "--publish", "multica:127.0.0.1:18080",
    ]


def main():
    with tempfile.TemporaryDirectory(prefix="multica-desktop-") as temporary:
        with native.native_transport(pathlib.Path(temporary)) as environment:
            subprocess.run(connect_command(verified_client()), env=environment, check=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
