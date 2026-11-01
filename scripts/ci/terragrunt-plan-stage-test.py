#!/usr/bin/env python3
"""Ensure private plan output can produce only fixed diagnostic labels."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import textwrap
import unittest

HELPER = Path(__file__).with_name("terragrunt-plan-stage.sh")
WORKFLOW = HELPER.parents[2] / ".github/workflows/terragrunt-plan.yml"
PLAN_RUNNER = HELPER.with_name("terragrunt-plan.sh")
MARKERS = {
    "": "nix",
    "::group::Kubeconfig setup": "kubeconfig",
    "::group::Kubernetes API check": "api",
    "::group::Argo CD bootstrap plan": "bootstrap",
    "::group::Argo CD Application registration plan": "app",
    "::group::AzureAD application registration plan": "azuread",
    "::group::Terraform plan Conftest policies": "policy",
}


class PrivatePlanStageTest(unittest.TestCase):
    def assert_stage(self, private_output, stage, reason="unknown", *,
                     azuread_report=None, azuread_unit=None):
        environment = dict(os.environ)
        if azuread_report is not None:
            environment["HOMELAB_AZUREAD_PLAN_REPORT_FILE"] = str(azuread_report)
        result = subprocess.run(["bash", str(HELPER)], input=private_output,
                                text=True, capture_output=True, timeout=5, check=False,
                                env=environment)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        expected = (f"Live plan last recognized stage: {stage}; details withheld.\n"
                    f"Live plan failure hint: {reason}; details withheld.\n")
        if azuread_unit is not None:
            expected += f"Live plan first failed AzureAD unit: {azuread_unit}; details withheld.\n"
        self.assertEqual(result.stdout, expected)

    def test_only_fixed_labels_leave_private_output(self):
        secret = "SYNTHETIC_PRIVATE_VALUE_DO_NOT_EMIT"
        for marker, stage in MARKERS.items():
            # Even an exact marker in secret output can disclose only a label.
            self.assert_stage(f"{secret}\n{marker}\n::error::{secret}\n{secret}", stage)
        for marker in list(MARKERS)[1:]:
            for forged in (marker + secret, secret + marker,
                           "\x1b[31m" + marker, marker + "$(echo " + secret + ")"):
                self.assert_stage(forged, "nix")
        self.assert_stage("\n".join(MARKERS), "policy")

    def test_only_fixed_reasons_leave_private_output(self):
        secret = "SYNTHETIC_PRIVATE_VALUE_DO_NOT_EMIT"
        fragments = {
            "AccessDenied": "aws-auth",
            "ExpiredToken": "aws-auth",
            "InvalidClientTokenId": "aws-auth",
            "the server has asked for the client to provide credentials": "kubernetes-auth",
            "Error from server (Unauthorized)": "kubernetes-auth",
            "Error from server (Forbidden)": "kubernetes-auth",
            "TLS handshake timeout": "network",
            "i/o timeout": "network",
            "context deadline exceeded": "network",
            "connection refused": "network",
            "Plugin did not respond": "provider",
            "Failed to load plugin schemas": "provider",
            "Failed to query available provider packages": "provider",
            "Failed to install provider": "provider",
        }
        for fragment, reason in fragments.items():
            with self.subTest(fragment=fragment):
                self.assert_stage(f"{secret}\n::group::Argo CD Application registration plan\n"
                                  f"{secret} {fragment} {secret}\n", "app", reason)
        self.assert_stage(f"::group::Terraform plan Conftest policies\n"
                          f"::error file={secret},line=1::{secret}", "policy", "policy")
        self.assert_stage(f"::error file={secret},line=1::{secret}", "nix")
        # First recognized fragment wins; arbitrary text never becomes a label.
        self.assert_stage(f"i/o timeout\nAccessDenied\n{secret}", "nix", "network")

    def test_azuread_failure_categories_and_private_report_unit_are_allowlisted(self):
        secret = "SYNTHETIC_PRIVATE_VALUE_DO_NOT_EMIT"
        fragments = {
            "Authorization_RequestDenied": "entra-authorization",
            "Insufficient privileges to complete the operation": "entra-authorization",
            "InvalidAuthenticationToken": "entra-authentication",
            "AADSTS700213": "entra-authentication",
            "Request_ResourceNotFound": "entra-resource-not-found",
            "404 Not Found": "entra-resource-not-found",
            "TooManyRequests": "entra-throttled",
            "429 Too Many Requests": "entra-throttled",
        }
        for fragment, reason in fragments.items():
            with self.subTest(fragment=fragment):
                self.assert_stage("::group::AzureAD application registration plan\n"
                                  f"{secret} {fragment} {secret}\n", "azuread", reason)

        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            report.write_text(json.dumps([{
                "Name": "fleet", "Result": "failed", "Cause": secret,
            }]))
            self.assert_stage("::group::AzureAD application registration plan\n"
                              f"{secret}\n", "azuread", azuread_report=report,
                              azuread_unit="fleet")

            for records in (
                [{"Name": "fleet", "Result": "succeeded", "Cause": secret}],
                [{"Name": "unknown", "Result": "failed", "Cause": secret}],
                [{"Name": "fleet", "Result": "failed", "Cause": secret},
                 {"Name": "grafana", "Result": "failed", "Cause": secret}],
            ):
                report.write_text(json.dumps(records))
                self.assert_stage("::group::AzureAD application registration plan\n"
                                  f"{secret}\n", "azuread", azuread_report=report,
                                  azuread_unit="fleet" if len(records) == 2 else None)
            report.write_text("not-json " + secret)
            self.assert_stage("::group::AzureAD application registration plan\n"
                              f"{secret}\n", "azuread", azuread_report=report)

    def test_azuread_plan_passes_the_private_report_only_to_terragrunt(self):
        runner = PLAN_RUNNER.read_text()
        self.assertIn('if [[ -n "${HOMELAB_AZUREAD_PLAN_REPORT_FILE:-}" ]]; then', runner)
        self.assertIn('--report-file "$HOMELAB_AZUREAD_PLAN_REPORT_FILE"', runner)
        self.assertIn('--report-format json', runner)
        self.assertIn('"${azuread_report_args[@]}" -- plan -lock=false -out plan.out -no-color', runner)

    def test_changed_azuread_inputs_never_skip_for_missing_credentials(self):
        runner = PLAN_RUNNER.read_text()
        section = runner.split('echo "::group::AzureAD application registration plan"\n', 1)[1]
        section = section.split('\necho "::endgroup::"', 1)[0]
        for stack_changed, inputs_changed, expected_code in (
            (True, False, 1), (False, True, 1), (False, False, 0)
        ):
            with self.subTest(stack_changed=stack_changed, inputs_changed=inputs_changed):
                script = ('set -euo pipefail\n'
                          'azuread_credentials_available() { return 1; }\n'
                          f'terragrunt_azuread_stack_changed() {{ return {0 if stack_changed else 1}; }}\n'
                          f'terragrunt_azuread_plan_inputs_changed() {{ return {0 if inputs_changed else 1}; }}\n'
                          + section)
                result = subprocess.run(["bash", "-c", script], text=True,
                                        capture_output=True, timeout=5, check=False)
                self.assertEqual(result.returncode, expected_code, result.stderr)
                self.assertEqual("Skipping AzureAD" in result.stdout, expected_code == 0)
                if expected_code:
                    self.assertIn("AzureAD credentials are required", result.stderr)

    def test_scope_diff_failure_cannot_skip_live_plan(self):
        workflow = WORKFLOW.read_text()
        scope = textwrap.dedent(workflow.split(
            "      - name: Detect Live Terragrunt Plan Scope\n", 1)[1]
            .split("\n      - name: Install Nix\n", 1)[0]
            .split("        run: |\n", 1)[1])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "README.md").write_text("fixture\n")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
            subprocess.run(["git", "-c", "user.name=Fixture",
                            "-c", "user.email=fixture@example.invalid",
                            "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"],
                           cwd=root, check=True)
            output = root / "github-output"
            result = subprocess.run(["bash", "-euo", "pipefail", "-c", scope],
                                    cwd=root, capture_output=True, text=True,
                                    env={**os.environ, "BASE_REF": "main",
                                         "GITHUB_OUTPUT": str(output)}, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unable to determine live Terragrunt plan scope", result.stderr)
            self.assertFalse(output.exists())

    def test_tailscale_policy_change_requires_live_plan(self):
        workflow = WORKFLOW.read_text()
        scope = textwrap.dedent(workflow.split(
            "      - name: Detect Live Terragrunt Plan Scope\n", 1)[1]
            .split("\n      - name: Install Nix\n", 1)[0]
            .split("        run: |\n", 1)[1])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "README.md").write_text("fixture\n")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
            commit = ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                      "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"]
            subprocess.run(commit, cwd=root, check=True)
            subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=root, check=True)
            policy = root / "scripts/config/tailscale-policy.json"
            policy.parent.mkdir(parents=True)
            policy.write_text("{}\n")
            subprocess.run(["git", "add", str(policy.relative_to(root))], cwd=root, check=True)
            subprocess.run(commit, cwd=root, check=True)
            output = root / "github-output"
            result = subprocess.run(["bash", "-euo", "pipefail", "-c", scope],
                                    cwd=root, capture_output=True, text=True,
                                    env={**os.environ, "BASE_REF": "main", "GITHUB_OUTPUT": str(output)},
                                    timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("requires-live-plan=true", output.read_text())

    def test_workflow_streams_plan_output_and_keeps_artifacts_private(self):
        workflow = WORKFLOW.read_text()
        run = workflow.split("      - name: Run Live Terragrunt Plan\n", 1)[1]
        run = run.split("\n  terragrunt-plan-skipped:", 1)[0]
        self.assertIn("HOMELAB_AZUREAD_PLAN_REPORT_FILE=\"$azuread_report\" nix develop --command bash <<'EOF'", run)
        self.assertNotIn('private_log', run)
        self.assertNotIn('details withheld', run)
        self.assertIn("trap 'rm -rf -- \"$private_dir\"' EXIT", run)
        self.assertIn('bash scripts/ci/terragrunt-plan.sh', run)
        self.assertNotIn('>/dev/null', PLAN_RUNNER.read_text().split('terragrunt plan -destroy', 1)[1].split('\n', 1)[0])


if __name__ == "__main__":
    unittest.main()
