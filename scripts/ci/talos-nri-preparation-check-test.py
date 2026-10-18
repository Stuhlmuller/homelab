#!/usr/bin/env python3
"""Keep Talos validation errors useful without printing generated secrets."""

import runpy
import subprocess
from pathlib import Path
from unittest.mock import patch

module = runpy.run_path(str(Path(__file__).with_name("talos-nri-preparation-check.py")))
run = module["run"]
secret = "a" * 64
with patch.object(module["subprocess"], "run", return_value=subprocess.CompletedProcess(
        args=[], returncode=1, stdout="sensitive output marker", stderr=f"invalid field\ntoken: {secret}")):
    try:
        run("talosctl", "validate", "--config", "candidate.yaml")
    except RuntimeError as error:
        message = str(error)
        assert "talosctl validate --config failed (exit 1)" in message
        assert "invalid field" in message and "token: [redacted]" in message
        assert secret not in message and "sensitive output marker" not in message
    else:
        raise AssertionError("Failed validation passed")

print("Talos NRI validation diagnostics are sanitized")
