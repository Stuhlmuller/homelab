#!/usr/bin/env python3
"""Fail-closed tests for the staged protected platform entry point."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / "scripts/ci/platform-maintenance-stage.sh"
SHA = "a" * 40


class PlatformStageTests(unittest.TestCase):
    def run_stage(self, stage):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            bin_dir = path / "bin"
            bin_dir.mkdir()
            (bin_dir / "gh").write_text(f"#!/bin/sh\nprintf '%s\\n' {SHA}\n")
            (bin_dir / "gh").chmod(0o700)
            marker = path / "external-command"
            for name in ("aws", "talosctl", "kubectl", "octelium"):
                executable = bin_dir / name
                executable.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 99\n")
                executable.chmod(0o700)
            env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
                       GITHUB_ACTIONS="true", GITHUB_REF="refs/heads/main",
                       GITHUB_SHA=SHA, EXPECTED_SHA=SHA, GITHUB_RUN_ID="123",
                       RUN_STAGE=stage)
            result = subprocess.run(["bash", str(STAGE)], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=10)
            return result, marker.exists()

    def test_unknown_stage_is_rejected_before_external_access(self):
        result, external = self.run_stage("talos-9.9.9")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(external)

    def test_disabled_config_blocks_all_mutating_stages(self):
        for stage in ("qualify", "owned-cleanup", "talos-1.11.6",
                      "talos-1.12.12", "talos-1.13.11", "talos-1.14.4",
                      "kubernetes-1.35.9"):
            with self.subTest(stage=stage):
                result, external = self.run_stage(stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(external)

    def test_upgrade_executor_requires_protected_inputs(self):
        source = STAGE.read_text()
        self.assertIn("platform-maintenance.py execute", source)
        self.assertIn("OCE_OCTELIUM_CLIENT_AUTH_TOKEN", source)
        self.assertIn("OCE_CONTROLPLANE_CONFIG_B64", source)
        self.assertIn("--receipt-dir \"$work/receipts\"", source)
        self.assertIn("--publish talos-api-ci.homelab:127.0.0.1:15000", source)

    def test_inspect_installs_clientless_kubeconfig_before_cluster_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            bin_dir = path / "bin"
            bin_dir.mkdir()
            trace = path / "trace"
            bash = shutil.which("bash")

            def executable(name, source):
                candidate = bin_dir / name
                candidate.write_text("#!/bin/sh\n" + source)
                candidate.chmod(0o700)

            executable("gh", f"printf '%s\\n' {SHA}\n")
            executable("aws", "case \"$*\" in\n"
                       "  *get-bucket-versioning*) echo Enabled;;\n"
                       "  *get-bucket-encryption*) echo aws:kms;;\n"
                       "  *) exit 99;;\n"
                       "esac\n")
            executable("bash", "case \"$1\" in\n"
                       "  scripts/ci/install-kubeconfig.sh) echo kubeconfig >>\"$TRACE\"; exit 0;;\n"
                       "  scripts/ci/install-octelium-client.sh) echo client >>\"$TRACE\"; exit 0;;\n"
                       "esac\n"
                       f"exec '{bash}' \"$@\"\n")
            executable("python3", "if [ \"$1\" = -I ]; then shift; fi\n"
                       "case \"$1\" in\n"
                       "  -) cat >/dev/null; exit 0;;\n"
                       "  scripts/platform-maintenance.py) echo inspect >>\"$TRACE\"; exit 42;;\n"
                       "esac\nexit 99\n")
            executable("sudo", "cat >/dev/null\n")
            client = path / ".local/bin/octelium"
            client.parent.mkdir(parents=True)
            client.write_text("#!/bin/sh\nexit 0\n")
            client.chmod(0o700)
            env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
                       HOME=str(path), TRACE=str(trace), GITHUB_ACTIONS="true",
                       GITHUB_REF="refs/heads/main", GITHUB_SHA=SHA,
                       EXPECTED_SHA=SHA, GITHUB_RUN_ID="123", RUN_STAGE="inspect",
                       OCTELIUM_AUTH_TOKEN="clientless-test-token",
                       OCE_OCTELIUM_CLIENT_AUTH_TOKEN="client-test-token",
                       OCE_TALOSCONFIG_B64="Zm9v")
            result = subprocess.run([bash, str(STAGE)], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 42, result.stderr)
            self.assertEqual(trace.read_text().splitlines(),
                             ["kubeconfig", "client", "inspect"])

    def test_cleanup_retains_attempt_before_running_firewall_helper(self):
        source = STAGE.read_text()
        self.assertLess(source.index('retain_result "$work/cleanup-attempt.json" cleanup-attempt'),
                        source.index('python3 scripts/network-policy-cleanup.py'))


if __name__ == "__main__":
    unittest.main()
