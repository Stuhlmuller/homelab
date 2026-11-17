#!/usr/bin/env python3
"""Ensure private apply output can produce only fixed phase and failure-hint labels."""
from pathlib import Path
import os
import subprocess
import tempfile
import textwrap
import unittest

HELPER = Path(__file__).with_name("terragrunt-apply-stage.sh")
WORKFLOW = HELPER.parents[2] / ".github/workflows/terragrunt-apply.yml"
APPLY_SCRIPT = HELPER.with_name("terragrunt-apply.sh")
MARKERS = {
    "": "nix",
    "::group::Kubeconfig setup": "kubeconfig",
    "::group::Kubernetes API check": "api",
    "::group::Terragrunt apply": "terragrunt",
    "::group::Targeted Argo CD apply prerequisites": "target-prerequisites",
    "::group::Targeted Argo CD Application state repair": "state-repair",
    "::group::Targeted Argo CD Application registration apply": "target-registration",
    "::group::Deleted Terragrunt unit state destroy: unit-name": "retired-units",
    "::group::OpenClaw legacy offsite bucket plan and apply": "backup-storage",
    "::group::Argo CD bootstrap apply": "bootstrap",
    "::group::AWS SSM parameter declaration plan and apply": "ssm",
    "::group::Langfuse blob storage plan and apply": "langfuse",
    "::group::Kubernetes node label apply": "node-labels",
    "::group::AzureAD application registration apply": "azuread",
    "::group::Argo CD Application registration apply": "argocd-apps",
    "::group::External Secrets AWS auth Secret state adoption": "external-secrets",
    "::group::Kubernetes secret materialization apply": "kubernetes-secrets",
}


class PrivateApplyStageTest(unittest.TestCase):
    def assert_phase(self, private_output, phase, hint="unknown"):
        result = subprocess.run(["bash", str(HELPER)], input=private_output,
                                text=True, capture_output=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout,
                         f"Production apply last recognized phase: {phase}; details withheld.\n"
                         f"Production apply failure hint: {hint}; details withheld.\n")

    def test_only_fixed_labels_leave_private_output(self):
        secret = "SYNTHETIC_PRIVATE_VALUE_DO_NOT_EMIT"
        for marker, phase in MARKERS.items():
            self.assert_phase(f"{secret}\n{marker}\n::error::{secret}\n{secret}", phase)
        for marker in list(MARKERS)[1:]:
            for forged in (marker + secret, secret + marker,
                           "\x1b[31m" + marker, marker + "$(echo " + secret + ")"):
                if marker.startswith("::group::Deleted Terragrunt"):
                    continue
                self.assert_phase(forged, "nix")
        self.assert_phase("\n".join(MARKERS), "kubernetes-secrets")

    def test_known_hints_never_emit_private_text(self):
        fragments = {
            "AccessDenied": "aws-auth",
            "ExpiredToken": "aws-auth",
            "InvalidClientTokenId": "aws-auth",
            "Error from server (Forbidden)": "kubernetes-auth",
            "the server has asked for the client to provide credentials": "kubernetes-auth",
            "Authorization_RequestDenied": "entra-auth",
            "AADSTS700024": "entra-auth",
            "TLS handshake timeout": "network",
            "connection refused": "network",
            "Failed to install provider": "provider",
            "Failed to query available provider packages": "provider",
            "Error downloading modules": "module-download",
            "Error acquiring the state lock": "state-lock",
            "another operation (install/upgrade/rollback) is in progress": "helm-operation",
            "cannot re-use a name that is still in use": "helm-operation",
            "Main advanced after dispatch; refusing to change live state.": "source-guard",
            "Unable to verify current main; refusing to change live state.": "source-guard",
            "::error file=private.json,line=1,col=1::private policy error": "policy",
        }
        for fragment, hint in fragments.items():
            with self.subTest(fragment=fragment):
                self.assert_phase(
                    "::group::Argo CD bootstrap apply\n"
                    f"PRIVATE_PREFIX {fragment} PRIVATE_SUFFIX $(false)",
                    "bootstrap", hint)

    def test_unknown_blank_and_unterminated_output(self):
        for private_output in ("", "\n", "PRIVATE_UNKNOWN_ERROR"):
            self.assert_phase(private_output, "nix")

    def test_hint_is_local_to_last_recognized_phase(self):
        self.assert_phase("::group::Kubernetes API check\nconnection refused\n"
                          "::group::Argo CD bootstrap apply\nPRIVATE_UNKNOWN",
                          "bootstrap")
        self.assert_phase("::group::Argo CD bootstrap apply\nAccessDenied\n"
                          "connection refused", "bootstrap", "aws-auth")
        self.assert_phase("::group::Argo CD bootstrap apply\nAccessDenied\n"
                          "::group::Argo CD bootstrap apply\nconnection refused",
                          "bootstrap", "network")

    def test_apply_script_keeps_inner_phase_markers(self):
        source = APPLY_SCRIPT.read_text()
        for marker in list(MARKERS)[4:]:
            self.assertIn(marker.rsplit(" unit-name", 1)[0], source)

    def test_workflow_tail_executes_only_the_verified_helper(self):
        workflow = WORKFLOW.read_text()
        tail = textwrap.dedent(workflow.split("\n          EOF\n", 1)[1])
        withheld_error = ("::error::Production apply failed; detailed output was withheld "
                          "because this is a public repository. Reproduce it from an approved local operator session.\n")
        secret = "SYNTHETIC_PRIVATE_VALUE_DO_NOT_EMIT"
        original = HELPER.read_text()
        variants = (
            original,
            ': > executed\ncat\n',
            ': > executed\ncat >&2\n',
            ': > executed\nif [[ ${GITHUB_ACTIONS:-} == true ]]; then cat; fi\n',
            None,
        )
        for helper_source, broken_shell in [(item, False) for item in variants] + [(original, True)]:
            with self.subTest(helper_source=helper_source, broken_shell=broken_shell), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                helper = root / "scripts/ci/terragrunt-apply-stage.sh"
                helper.parent.mkdir(parents=True)
                if helper_source is not None:
                    helper.write_text(helper_source)
                private_log = root / "private.log"
                private_log.write_text(f"{secret}\n::group::Kubernetes API check\n{secret}\n")
                env = dict(os.environ, CI="true", GITHUB_ACTIONS="true")
                if broken_shell:
                    binaries = root / "bin"
                    binaries.mkdir()
                    shell = binaries / "bash"
                    shell.write_text("#!/bin/sh\nexit 7\n")
                    shell.chmod(0o700)
                    env["PATH"] = str(binaries) + os.pathsep + env["PATH"]
                result = subprocess.run(
                    ["/bin/bash", "-euo", "pipefail", "-c", 'private_log="$1"\nif true\n' + tail,
                     "failure-tail-test", str(private_log)],
                    cwd=root, env=env,
                    text=True, capture_output=True, timeout=5, check=False)
                expected = withheld_error
                if helper_source == original and not broken_shell:
                    expected = ("Production apply last recognized phase: api; details withheld.\n"
                                "Production apply failure hint: unknown; details withheld.\n" + expected)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, expected)
                self.assertEqual(result.stderr, "")
                self.assertFalse((root / "executed").exists())


if __name__ == "__main__":
    unittest.main()
