#!/usr/bin/env python3
"""Exercise the declared Octelium plan policy against security fixtures."""

import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "docs/examples/octelium/homelab-services.yaml"
USER = "homelab-ci-plan"
SERVICE = "kubernetes-api-ci.default"
READ_VERBS = {"get", "list", "watch"}
WRITE_VERBS = {"create", "update", "patch", "delete", "deletecollection"}


def policy_rules() -> list[dict]:
    rendered = subprocess.run(
        ["yq", "ea", "-o=json", "-I=0", "[.]", str(CATALOG)],
        capture_output=True, text=True, check=True,
    )
    resources = json.loads(rendered.stdout)
    policies = [item for item in resources if item.get("kind") == "Policy"
                and item["metadata"]["name"] == "homelab-ci-kubernetes-api-plan-access"]
    assert len(policies) == 1
    return policies[0]["spec"]["rules"]


def matches(condition: dict, request: dict) -> bool:
    if "all" in condition:
        return all(matches(part, request) for part in condition["all"]["of"])
    if "any" in condition:
        return any(matches(part, request) for part in condition["any"]["of"])

    expression = condition["match"]
    known = {
        'ctx.user.metadata.name == "homelab-ci-plan"': request["user"] == USER,
        'ctx.user.spec.type == "WORKLOAD"': request["user_type"] == "WORKLOAD",
        'ctx.session.status.type == "CLIENTLESS"': request["session"] == "CLIENTLESS",
        'ctx.service.metadata.name == "kubernetes-api-ci.default"': request["service"] == SERVICE,
        'ctx.service.spec.mode == "KUBERNETES"': request["mode"] == "KUBERNETES",
        'ctx.request.kubernetes.verb in ["create", "update", "patch", "delete", "deletecollection"]': request["verb"] in WRITE_VERBS,
        '!has(ctx.request.kubernetes.http.queryParams.dryRun) || ctx.request.kubernetes.http.queryParams.dryRun != "All"': request["dry_run"] != "All",
        'has(ctx.request.kubernetes.subresource)': "subresource" in request,
        '!has(ctx.request.kubernetes.subresource)': "subresource" not in request,
        'ctx.request.kubernetes.http.method in ["GET", "HEAD"] && ctx.request.kubernetes.verb in ["get", "list", "watch"]': request["method"] in {"GET", "HEAD"} and request["verb"] in READ_VERBS,
        'ctx.request.kubernetes.verb in ["create", "update", "patch", "delete", "deletecollection"] && ctx.request.kubernetes.http.queryParams.dryRun == "All"': request["verb"] in WRITE_VERBS and request["dry_run"] == "All",
    }
    if expression not in known:
        raise AssertionError(f"Unrecognized plan policy condition: {expression}")
    return known[expression]


class PlanPolicyFixtures(unittest.TestCase):
    def test_read_and_dry_run_boundary(self) -> None:
        rules = policy_rules()
        self.assertEqual(
            [(rule["name"], rule["effect"], rule.get("priority")) for rule in rules],
            [("deny-non-dry-run-writes", "DENY", -4),
             ("deny-subresources", "DENY", -4),
             ("read-or-dry-run", "ALLOW", None)],
        )

        fixtures = [
            ("ordinary get, omitted subresource", "GET", "get", None, None, True),
            ("list", "GET", "list", None, None, True),
            ("watch", "GET", "watch", None, None, True),
            ("dry-run patch, omitted subresource", "PATCH", "patch", None, "All", True),
            ("live patch", "PATCH", "patch", None, None, False),
            ("other dry-run value", "PATCH", "patch", None, "None", False),
            ("GET exec", "GET", "get", "exec", None, False),
            ("GET attach", "GET", "get", "attach", None, False),
            ("GET portforward", "GET", "get", "portforward", None, False),
            ("GET proxy", "GET", "get", "proxy", None, False),
            ("dry-run exec", "POST", "create", "exec", "All", False),
            ("unknown GET verb", "GET", "connect", None, None, False),
        ]
        for label, method, verb, subresource, dry_run, expected in fixtures:
            request = {"user": USER, "user_type": "WORKLOAD", "session": "CLIENTLESS",
                       "service": SERVICE, "mode": "KUBERNETES", "method": method,
                       "verb": verb, "dry_run": dry_run}
            if subresource is not None:
                request["subresource"] = subresource
            denied = any(matches(rule["condition"], request) for rule in rules
                         if rule["effect"] == "DENY")
            allowed = any(matches(rule["condition"], request) for rule in rules
                          if rule["effect"] == "ALLOW")
            with self.subTest(label=label):
                self.assertEqual(allowed and not denied, expected)


if __name__ == "__main__":
    unittest.main()
