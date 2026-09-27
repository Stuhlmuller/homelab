#!/usr/bin/env python3
"""Verify the desktop helper keeps Multica behind scoped Octelium transport."""
import importlib.util
import pathlib
import subprocess
from unittest.mock import patch

source = pathlib.Path(__file__).resolve().parents[1] / "multica-desktop-connect.py"
spec = importlib.util.spec_from_file_location("desktop", source)
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)

expected = [
    "/pinned/octelium", "connect", "--domain", "stinkyboi.com", "--implementation",
    "gvisor", "--no-dns", "--publish", "multica:127.0.0.1:18080",
]
assert desktop.connect_command("/pinned/octelium") == expected
with patch.object(desktop.shutil, "which", return_value="/pinned/octelium"), patch.object(
    desktop.subprocess, "run",
    return_value=subprocess.CompletedProcess(
        [], 0, "releaseVersion: v0.35.0\ngitCommit: 5e4eb3e36911ba4f66f5f43df2cc4b264211c4ce\n", "",
    ),
):
    assert desktop.verified_client() == "/pinned/octelium"

print("Multica desktop transport checks passed")
