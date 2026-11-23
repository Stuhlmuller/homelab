#!/usr/bin/env python3
"""Exercise the Octelium CI rotation boundary without live credentials."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/octelium-ci-credential.sh"
MOCK = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
name = Path(sys.argv[0]).name
page = int(args[args.index("--page") + 1]) if "--page" in args else 1
with open(os.environ["OCE_TEST_LOG"], "a", encoding="utf-8") as log:
    log.write(name + " " + " ".join(args) + "\n")
variant = os.environ.get("OCE_TEST_VARIANT", "success")
if name == "gh":
    if args[:2] == ["secret", "set"]:
        token = sys.stdin.read()
        if not token:
            sys.exit(1)
        if (variant == "github_second_env_fail" and
                args[2] == "OCTELIUM_CI_AUTH_TOKEN" and
                args[-1] == "homelab-production"):
            sys.exit(1)
    if variant == "preflight_delete_fail" and args[:3] == ["api", "--method", "DELETE"]:
        calls = Path(os.environ["OCE_TEST_LOG"]).read_text(encoding="utf-8")
        if calls.count("gh api --method DELETE") == 1:
            sys.exit(1)
    sys.exit(0)
if name == "sleep":
    sys.exit(0)
if args[0] == "get":
    resource = args[1]
    if resource == "user":
        result = {"metadata": {"name": "homelab-ci"}, "spec": {
            "type": "WORKLOAD", "session": {
                "clientlessDuration": {"days": 30},
                "accessTokenDuration": {"days": 30}}}}
        if variant == "user_disabled":
            result["spec"]["isDisabled"] = True
        if variant == "clientless_duration_drift":
            result["spec"]["session"]["clientlessDuration"]["days"] = 31
        if variant == "access_token_duration_drift":
            result["spec"]["session"]["accessTokenDuration"]["days"] = 31
    elif resource == "policy":
        if args[2] == "homelab-ci-kubernetes-api-plan-access":
            def match(expression):
                return {"match": expression}

            plan_user = 'ctx.user.metadata.name == "homelab-ci-plan"'
            service = 'ctx.service.metadata.name == "kubernetes-api-ci.default"'
            write_verb = 'ctx.request.kubernetes.verb in ["create", "update", "patch", "delete", "deletecollection"]'
            rules = [
                {"name": "deny-non-dry-run-writes", "effect": "DENY", "priority": -4,
                 "condition": {"all": {"of": [
                     match(plan_user), match(service), match(write_verb),
                     match('!has(ctx.request.kubernetes.http.queryParams.dryRun) || ctx.request.kubernetes.http.queryParams.dryRun != "All"')
                 ]}}},
                {"name": "deny-subresources", "effect": "DENY", "priority": -4,
                 "condition": {"all": {"of": [
                     match(plan_user), match(service),
                     match('has(ctx.request.kubernetes.subresource)')
                 ]}}},
                {"name": "read-or-dry-run", "effect": "ALLOW",
                 "condition": {"all": {"of": [
                     match(plan_user), match('ctx.user.spec.type == "WORKLOAD"'),
                     match('ctx.session.status.type == "CLIENTLESS"'),
                     match(service), match('ctx.service.spec.mode == "KUBERNETES"'),
                     match('!has(ctx.request.kubernetes.subresource)'),
                     {"any": {"of": [
                         match('ctx.request.kubernetes.http.method in ["GET", "HEAD"] && ctx.request.kubernetes.verb in ["get", "list", "watch"]'),
                         match('ctx.request.kubernetes.verb in ["create", "update", "patch", "delete", "deletecollection"] && ctx.request.kubernetes.http.queryParams.dryRun == "All"')
                     ]}}
                 ]}}}
            ]
            if variant == "staged_plan_policy_drift":
                rules[-1]["condition"] = {"all": {"of": []}}
            result = {"metadata": {"name": args[2]}, "spec": {"rules": rules}}
        else:
            matches = [
                'ctx.user.metadata.name == "homelab-ci"',
                'ctx.user.spec.type == "WORKLOAD"',
                'ctx.session.status.type == "CLIENTLESS"',
                'ctx.service.metadata.name == "kubernetes-api-ci.default"',
                'ctx.service.spec.mode == "KUBERNETES"',
            ]
            rules = [{"effect": "ALLOW", "condition": {"all": {"of": [
                {"match": match} for match in matches]}}}]
            if variant == "policy_drift":
                rules.append({"effect": "ALLOW", "condition": {"all": {"of": []}}})
            result = {"metadata": {"name": "homelab-ci-kubernetes-api-access"},
                      "spec": {"rules": rules}}
            if variant == "policy_disabled":
                result["spec"]["isDisabled"] = True
    elif resource == "service":
        result = {"metadata": {"name": "kubernetes-api-ci.default"}, "spec": {
            "isPublic": True, "mode": "KUBERNETES", "port": 6443,
            "authorization": {"policies": ["homelab-ci-kubernetes-api-access"]},
            "config": {"upstream": {"url": "https://10.1.0.199:6443"},
                       "kubernetes": {"kubeconfig": {"fromSecret": "homelab-ci-kubeconfig"}}}}}
        if variant == "service_drift":
            result["spec"]["isPublic"] = False
        if variant == "anonymous_service":
            result["spec"]["isAnonymous"] = True
        if variant == "unreviewed_service_policy":
            result["spec"]["authorization"]["policies"].append("allow-all-public")
        if variant == "duplicate_service_policy":
            result["spec"]["authorization"]["policies"].append(
                "homelab-ci-kubernetes-api-access")
        if variant == "staged_plan_service_policy":
            result["spec"]["authorization"]["policies"].append(
                "homelab-ci-kubernetes-api-plan-access")
        if variant == "staged_plan_policy_drift":
            result["spec"]["authorization"]["policies"].append(
                "homelab-ci-kubernetes-api-plan-access")
    elif resource == "creds":
        target = {"metadata": {"name": "homelab-ci"}, "spec": {
            "user": "homelab-ci", "type": "ACCESS_TOKEN",
            "sessionType": "CLIENTLESS",
            "authorization": {"policies": ["homelab-ci-kubernetes-api-access"]}}}
        if variant == "credential_short_page":
            items = ([{"metadata": {"name": f"other-{i}"}}
                     for i in range(100)] if page == 1 else
                     [target] if page == 2 else [])
        elif variant == "repeated_credential_page":
            items = [target]
        else:
            items = [target] if page == 1 else []
        result = {"items": items}
        total = (101 if variant == "credential_short_page" else
                 2 if variant == "incomplete_meta" else 1)
        has_more = variant in ("credential_short_page", "repeated_credential_page") and page == 1
    elif resource == "sessions":
        if variant == "session_short_page":
            items = ([{"metadata": {"name": f"old-{i}"}}
                     for i in range(100)] if page == 1 else
                     [{"metadata": {"name": "old-last"}}] if page == 2 else [])
        elif variant == "repeated_session_page":
            items = [{"metadata": {"name": "old-session"}}]
        else:
            items = [{"metadata": {"name": "old-session"}}] if page == 1 else []
        result = {"items": items}
        total = 101 if variant == "session_short_page" else 1
        has_more = variant in ("session_short_page", "repeated_session_page") and page == 1
    else:
        sys.exit(2)
    if resource in ("creds", "sessions"):
        result["listResponseMeta"] = {"itemsPerPage": 100,
                                      "totalCount": total}
        if page > 1:
            result["listResponseMeta"]["page"] = page - 1
        if has_more:
            result["listResponseMeta"]["hasMore"] = True
    print(json.dumps(result))
elif args[:2] == ["create", "cred"]:
    print(json.dumps({"token": "test-" + "x" * 50}))
elif args[0] in ("apply", "delete"):
    pass
else:
    sys.exit(2)
'''


class RotationBoundaryTest(unittest.TestCase):
    def run_helper(self, variant="success", *args):
        with tempfile.TemporaryDirectory() as temp:
            fake_bin = Path(temp) / "bin"
            fake_bin.mkdir()
            mock = fake_bin / "mock"
            mock.write_text(MOCK, encoding="utf-8")
            mock.chmod(0o755)
            for command in ("octeliumctl", "gh", "sleep"):
                (fake_bin / command).symlink_to(mock)
            log = Path(temp) / "calls"
            env = os.environ.copy()
            env.update(PATH=f"{fake_bin}:{env['PATH']}", OCE_TEST_LOG=str(log),
                       OCE_TEST_VARIANT=variant, TMPDIR=temp)
            result = subprocess.run(["bash", str(HELPER), *args], cwd=ROOT,
                                    env=env, text=True, capture_output=True,
                                    check=False)
            self.assertEqual(list(Path(temp).glob("octelium-ci-credential.*.json")), [])
            return result, (log.read_text(encoding="utf-8").splitlines()
                            if log.exists() else [])

    def test_rotation_checks_resources_without_catalog_apply(self):
        result, calls = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("octeliumctl apply", "\n".join(calls))
        self.assertTrue(any(call.startswith("octeliumctl create cred") for call in calls))
        self.assertFalse(any("--page 2" in call for call in calls))
        self.assertEqual(sum("gh secret set OCTELIUM_CI_AUTH_TOKEN" in call
                             for call in calls), 2)
        self.assertNotIn("test-", result.stdout + result.stderr)

    def test_policy_drift_stops_before_session_reset_or_rotation(self):
        for variant in ("policy_drift", "policy_disabled", "service_drift",
                        "anonymous_service", "unreviewed_service_policy",
                        "duplicate_service_policy", "staged_plan_policy_drift"):
            with self.subTest(variant=variant):
                result, calls = self.run_helper(variant)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("differs", result.stderr)
                self.assertFalse(any(call.startswith("octeliumctl delete") or
                                     call.startswith("octeliumctl create") or
                                     call.startswith("gh secret set") for call in calls))

    def test_reviewed_staged_service_policy_is_allowed(self):
        result, calls = self.run_helper("staged_plan_service_policy")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(call.startswith("octeliumctl create cred") for call in calls))

    def test_staged_policy_fixture_matches_catalog(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / "octeliumctl"
            fake.write_text(MOCK, encoding="utf-8")
            fake.chmod(0o755)
            env = os.environ.copy()
            env["OCE_TEST_LOG"] = str(Path(temp) / "calls")
            observed = subprocess.run(
                [str(fake), "get", "policy", "homelab-ci-kubernetes-api-plan-access"],
                env=env, text=True, capture_output=True, check=True,
            )
        catalog = subprocess.run(
            ["yq", "ea", "-o=json", "-I=0", "[.]",
             str(ROOT / "docs/examples/octelium/homelab-services.yaml")],
            text=True, capture_output=True, check=True,
        )
        expected = [item for item in json.loads(catalog.stdout)
                    if item.get("kind") == "Policy" and item["metadata"]["name"]
                    == "homelab-ci-kubernetes-api-plan-access"]
        self.assertEqual(len(expected), 1)
        self.assertEqual(json.loads(observed.stdout)["spec"]["rules"],
                         expected[0]["spec"]["rules"])

    def test_user_duration_drift_stops_before_session_reset_or_rotation(self):
        for variant in ("clientless_duration_drift", "access_token_duration_drift"):
            with self.subTest(variant=variant):
                result, calls = self.run_helper(variant)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("dedicated CI access contract", result.stderr)
                self.assertFalse(any(call.startswith("octeliumctl delete") or
                                     call.startswith("octeliumctl create") or
                                     call.startswith("gh secret set") for call in calls))

    def test_short_server_pages_are_fully_consumed(self):
        result, calls = self.run_helper("credential_short_page")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any("get creds" in call and "--page 2" in call for call in calls))
        self.assertTrue(any("create cred" in call and "--rotate" in call for call in calls))
        result, calls = self.run_helper("session_short_page")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any("get sessions" in call and "--page 2" in call for call in calls))
        self.assertEqual(sum(call.startswith("octeliumctl delete session") for call in calls), 101)

    def test_repeated_pages_fail_closed_before_session_reset(self):
        for variant in ("repeated_credential_page", "repeated_session_page"):
            with self.subTest(variant=variant):
                result, calls = self.run_helper(variant)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("duplicate Octelium", result.stderr)
                self.assertFalse(any(call.startswith("octeliumctl delete") or
                                     call.startswith("octeliumctl create") for call in calls))

    def test_catalog_apply_is_explicit(self):
        result, calls = self.run_helper("success", "--dry-run")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("would apply", result.stdout)
        self.assertEqual(calls, [])
        result, calls = self.run_helper("success", "--dry-run", "--apply-catalog")
        self.assertEqual(result.returncode, 0)
        self.assertIn("would apply", result.stdout)
        self.assertEqual(calls, [])
        result, calls = self.run_helper("success", "--apply-catalog")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(call.startswith("octeliumctl apply") for call in calls))

    def test_sessions_only_rejects_catalog_apply_in_either_order(self):
        for args in (("--delete-user-sessions-only", "--apply-catalog"),
                     ("--apply-catalog", "--delete-user-sessions-only")):
            with self.subTest(args=args):
                result, calls = self.run_helper("success", *args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("cannot be combined", result.stderr)
                self.assertEqual(calls, [])

    def test_second_environment_failure_reports_recovery(self):
        result, calls = self.run_helper("github_second_env_fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rerun rotation for both environments", result.stderr)
        self.assertEqual(sum("gh secret set OCTELIUM_CI_AUTH_TOKEN" in call and
                             call.endswith("homelab-production") for call in calls), 5)
        self.assertNotIn("test-", result.stdout + result.stderr)

    def test_failed_preflight_retries_temp_secret_cleanup_on_exit(self):
        result, calls = self.run_helper("preflight_delete_fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sum(call.startswith("gh api --method DELETE")
                             for call in calls), 2)
        self.assertFalse(any(call.startswith("octeliumctl create") or
                             call.startswith("octeliumctl delete") for call in calls))
        self.assertNotIn("test-", result.stdout + result.stderr)

    def test_incomplete_metadata_stops_before_rotation(self):
        result, calls = self.run_helper("incomplete_meta")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("incomplete Octelium", result.stderr)
        self.assertFalse(any(call.startswith("octeliumctl delete") or
                             call.startswith("octeliumctl create") for call in calls))

    def test_disabled_user_allows_session_revocation_only(self):
        result, calls = self.run_helper("user_disabled", "--delete-user-sessions-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(call.startswith("octeliumctl delete session") for call in calls))
        self.assertFalse(any(call.startswith("octeliumctl create") for call in calls))
        result, calls = self.run_helper("user_disabled")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call.startswith("gh secret set") for call in calls))


if __name__ == "__main__":
    unittest.main()
