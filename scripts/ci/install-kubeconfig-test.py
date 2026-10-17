#!/usr/bin/env python3
"""Check the tokenless CI lane and refuse overwriting operator credentials."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class KubeconfigTests(unittest.TestCase):
    def test_tailscale_lane_has_fixed_verified_endpoint_and_no_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "kubectl"
            binary.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['HOME'])
with (root / 'calls').open('a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
(root / '.kube/config').write_text('tokenless fixture')
""")
            binary.chmod(0o700)
            env = dict(os.environ, HOME=directory, PATH=f"{directory}:{os.environ['PATH']}",
                       GITHUB_ACTIONS="true", OCTELIUM_AUTH_TOKEN="must-not-be-used",
                       KUBE_API_SERVER_URL="https://untrusted.invalid")
            result = subprocess.run(["bash", str(ROOT / "scripts/ci/install-kubeconfig.sh"), "--tailscale"],
                                    env=env, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
            self.assertEqual(calls[0], ["config", "set-cluster", "homelab-ci",
                                       "--server=https://homelab-tailscale-operator.tail67beb.ts.net"])
            self.assertIn(["config", "set-credentials", "homelab-ci"], calls)
            self.assertFalse(any("--token" in arg or "insecure" in arg for call in calls for arg in call))
            self.assertEqual((root / ".kube/config").stat().st_mode & 0o777, 0o600)
            second = subprocess.run(["bash", str(ROOT / "scripts/ci/install-kubeconfig.sh"), "--tailscale"],
                                    env=env, text=True, capture_output=True, check=False)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("Refusing to replace", second.stderr)
            self.assertEqual(len((root / "calls").read_text().splitlines()), len(calls))

    def test_plan_write_rbac_requires_dry_run_admission(self):
        rendered = subprocess.check_output(["kubectl", "kustomize", str(ROOT / "clusters/homelab/apps/tailscale")], text=True)
        resources = json.loads(subprocess.check_output(["yq", "ea", "-o=json", "[.]"], input=rendered, text=True))
        policy = next(item for item in resources if item["kind"] == "ValidatingAdmissionPolicy")
        binding = next(item for item in resources if item["kind"] == "ValidatingAdmissionPolicyBinding")
        self.assertEqual(policy["spec"]["failurePolicy"], "Fail")
        self.assertEqual(policy["spec"]["matchConditions"][0]["expression"], "'tag:homelab-ci-plan' in request.userInfo.groups")
        self.assertEqual(policy["spec"]["validations"][0]["expression"], "request.dryRun == true")
        self.assertEqual(binding["spec"]["policyName"], policy["metadata"]["name"])
        self.assertEqual(binding["spec"]["validationActions"], ["Deny"])
        role = next(item for item in resources if item["kind"] == "Role")
        self.assertEqual(role["metadata"]["namespace"], "argocd")
        self.assertEqual(role["rules"], [{"apiGroups": ["argoproj.io"], "resources": ["applications"], "verbs": ["create", "patch"]}])
        subjects = [subject["name"] for item in resources if item["kind"] in ("RoleBinding", "ClusterRoleBinding") for subject in item["subjects"]]
        self.assertNotIn("tag:homelab-ci-cordium", subjects)


if __name__ == "__main__":
    unittest.main()
