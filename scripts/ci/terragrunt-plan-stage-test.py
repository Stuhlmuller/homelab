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

    def test_workflow_tail_executes_only_the_verified_helper(self):
        # Execute the actual failure tail; no Nix, credentials, or live commands.
        workflow = WORKFLOW.read_text()
        tail = textwrap.dedent(workflow.split("\n          EOF\n", 1)[1]
                               .split("\n  terragrunt-plan-skipped:", 1)[0])
        withheld_error = ("::error::Live plan failed; detailed output was withheld "
                          "because this is a public repository. Reproduce it locally.\n")
        secret = "SYNTHETIC_PRIVATE_VALUE_DO_NOT_EMIT"
        original = HELPER.read_text()
        variants = (
            original,
            ': > executed\ncat\n',
            ': > executed\ncat >&2\n',
            ': > executed\nif [[ ${GITHUB_ACTIONS:-} == true ]]; then cat; fi\n',
            None,
        )
        for helper_source in variants:
            with self.subTest(helper_source=helper_source), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                sha256sum = root / "sha256sum"
                sha256sum.write_text("""#!/usr/bin/env python3
import hashlib
import sys

if sys.argv[1:] != ["--check", "--status"]:
    raise SystemExit(2)
try:
    expected, path = sys.stdin.read().strip().split(None, 1)
    actual = hashlib.sha256(open(path, "rb").read()).hexdigest()
except (OSError, ValueError):
    raise SystemExit(1)
raise SystemExit(0 if actual == expected else 1)
""")
                sha256sum.chmod(0o700)
                helper = root / "scripts/ci/terragrunt-plan-stage.sh"
                helper.parent.mkdir(parents=True)
                if helper_source is not None:
                    helper.write_text(helper_source)
                private_log = root / "private.log"
                private_log.write_text(f"{secret}\n::group::Kubernetes API check\n{secret}\n")
                result = subprocess.run(
                    ["bash", "-euo", "pipefail", "-c", 'private_log="$1"\nif true\n' + tail,
                     "failure-tail-test", str(private_log)],
                    cwd=root, env=dict(os.environ, CI="true", GITHUB_ACTIONS="true",
                                       PATH=str(root) + os.pathsep + os.environ["PATH"]),
                    text=True, capture_output=True, timeout=5, check=False)
                expected = withheld_error
                if helper_source == original:
                    expected = ("Live plan last recognized stage: api; details withheld.\n"
                                "Live plan failure hint: unknown; details withheld.\n" + expected)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, expected)
                self.assertEqual(result.stderr, "")
                self.assertFalse((root / "executed").exists())


if __name__ == "__main__":
    unittest.main()
