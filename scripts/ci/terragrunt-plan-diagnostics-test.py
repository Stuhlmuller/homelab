#!/usr/bin/env python3
"""Exercise stage-only output with synthetic private logs and a stubbed wrapper."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("diagnostics", HERE / "terragrunt-plan-diagnostics.py")
DIAGNOSTICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAGNOSTICS)
PRIVATE = "synthetic-private-output-never-publish"


def notice(stage):
    return (f"::error::Live plan failed; last entered stage: {stage}. "
            "Detailed output withheld because this is a public repository.\n")


class DiagnosticsTests(unittest.TestCase):
    def test_last_exact_marker_and_default(self):
        self.assertEqual(DIAGNOSTICS.last_stage(iter(())), "nix-setup")
        for stage in DIAGNOSTICS.STAGES:
            with self.subTest(stage=stage):
                lines = iter([b"homelab-plan-stage: kubeconfig\n",
                              f"homelab-plan-stage: {stage}\n".encode(), PRIVATE.encode()])
                self.assertEqual(DIAGNOSTICS.last_stage(lines), stage)
        self.assertEqual(DIAGNOSTICS.last_stage([b"homelab-plan-stage: policy"]), "policy")

    def test_arbitrary_lines_and_marker_lookalikes_cannot_be_output(self):
        invalid = [
            PRIVATE.encode(), b"homelab-plan-stage: " + PRIVATE.encode(),
            b"prefix homelab-plan-stage: policy\n", b" homelab-plan-stage: policy\n",
            b"homelab-plan-stage: policy suffix\n", b"homelab-plan-stage: policy\r\n",
            b"\x1b[0mhomelab-plan-stage: policy\n", b"homelab-plan-stage: policy\x00\n",
            b"\xff\xfe\n", b"X" * 1_000_000 + b"homelab-plan-stage: policy\n",
        ]
        self.assertEqual(DIAGNOSTICS.last_stage(
            iter([b"homelab-plan-stage: bootstrap-plan\n", *invalid])), "bootstrap-plan")

    def test_cli_never_echoes_private_lines_or_invalid_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / PRIVATE
            path.write_bytes(b"homelab-plan-stage: application-json\npassword: <synthetic-fixture>\n"
                             + PRIVATE.encode() + b"\n\xff\xfe\n")
            for arguments, stage in [([str(path)], "application-json"),
                                     ([str(path) + "-missing"], "unavailable"),
                                     ([directory], "unavailable"),
                                     ([str(path), PRIVATE], "unavailable"),
                                     ([], "unavailable")]:
                with self.subTest(stage=stage, count=len(arguments)):
                    result = subprocess.run([sys.executable, str(HERE / "terragrunt-plan-diagnostics.py"),
                                             *arguments], capture_output=True, text=True, check=False)
                    self.assertEqual(result.stdout, notice(stage))
                    self.assertEqual(result.stderr, "")
                    self.assertNotIn(directory, result.stdout)
                    self.assertNotIn(PRIVATE, result.stdout)

    def test_workflow_wrapper_withholds_failure_and_removes_private_log(self):
        self.run_wrapper(f'echo "{PRIVATE}"; exit 9\n', notice("kubeconfig"), 1)

    def test_workflow_wrapper_success_remains_unchanged(self):
        self.run_wrapper(f'echo "{PRIVATE}"\n', "Live plan and policy checks passed; details withheld.\n", 0)

    def test_workflow_wrapper_read_error_still_fails_without_raw_output(self):
        self.run_wrapper('rm -f "$TMPDIR"/*; exit 9\n', notice("unavailable"), 1)

    def run_wrapper(self, install_body, expected, returncode):
        workflow = (HERE.parents[1] / ".github/workflows/terragrunt-plan.yml").read_text()
        start = workflow.index('          private_log="$(mktemp)"')
        end = workflow.index("\n  terragrunt-plan-skipped:", start)
        wrapper = textwrap.dedent(workflow[start:end])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts/ci"
            scripts.mkdir(parents=True)
            (scripts / "terragrunt-plan-diagnostics.py").write_bytes(
                (HERE / "terragrunt-plan-diagnostics.py").read_bytes())
            (scripts / "install-kubeconfig.sh").write_text(install_body)
            (scripts / "terragrunt-plan.sh").write_text(f'echo "{PRIVATE}"\n')
            binaries = root / "bin"
            binaries.mkdir()
            for name, body in [("nix", "exec bash\n"), ("kubectl", "exit 0\n")]:
                path = binaries / name
                path.write_text("#!/bin/sh\n" + body)
                path.chmod(0o700)
            logs = root / "logs"
            logs.mkdir()
            environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                               TMPDIR=str(logs))
            result = subprocess.run(["bash", "-c", wrapper], cwd=root, env=environment,
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, returncode)
            self.assertEqual(result.stdout, expected)
            self.assertEqual(result.stderr, "")
            self.assertEqual(list(logs.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
