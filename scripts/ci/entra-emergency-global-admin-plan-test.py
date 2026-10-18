#!/usr/bin/env python3
"""Exercise the offline Entra emergency-administrator saved-plan guard."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts/verify-entra-emergency-global-admin-plan.py"
SECRET = "SYNTHETIC_PRIVATE_VALUE_DO_NOT_EMIT"
ROLE_ID = "62e90394-69f5-4237-9190-012177145e10"


def resource(address, resource_type, after, after_unknown, after_sensitive=None):
    return {
        "address": address,
        "mode": "managed",
        "type": resource_type,
        "change": {
            "actions": ["create"], "before": None, "after": after,
            "after_unknown": after_unknown, "after_sensitive": after_sensitive or {},
        },
    }


def valid_plan():
    return {
        "resource_changes": [
            {"address": "data.azuread_domains.tenant", "mode": "data", "type": "azuread_domains",
             "change": {"actions": ["read"], "before": None, "after": {"domains": [{
                 "domain_name": "example.onmicrosoft.com", "initial": True, "verified": True,
                 "authentication_type": "Managed",
             }]}}},
            {"address": "data.ignore.noop", "mode": "data", "type": "example",
             "change": {"actions": ["no-op"], "before": {}, "after": {}}},
            resource("random_password.initial", "random_password", {
                "length": 40, "min_lower": 3, "min_upper": 3, "min_numeric": 3,
                "min_special": 3, "override_special": "!@#%*-_+=",
            }, {"result": True}, {"result": True}),
            resource("azuread_user.this", "azuread_user", {
                "user_principal_name": "homelab-emergency-admin@example.onmicrosoft.com",
                "display_name": "Homelab emergency administrator",
                "mail_nickname": "homelab-emergency-admin",
                "account_enabled": True,
                "force_password_change": True,
                "disable_strong_password": False,
                "disable_password_expiration": True,
            }, {"object_id": True, "password": True}, {"password": True}),
            resource("azuread_directory_role_assignment.global_administrator",
                     "azuread_directory_role_assignment", {
                         "role_id": ROLE_ID,
                         "directory_scope_id": "/",
                     }, {"principal_object_id": True}),
        ],
        "configuration": {"root_module": {"resources": [
            {"address": "random_password.initial", "expressions": {}},
            {"address": "azuread_user.this", "expressions": {
                "user_principal_name": {"references": ["local.user_principal_name"]},
                "password": {"references": [
                    "random_password.initial.result", "random_password.initial",
                ]},
            }},
            {"address": "azuread_directory_role_assignment.global_administrator", "expressions": {
                "principal_object_id": {"references": [
                    "azuread_user.this.object_id", "azuread_user.this",
                ]},
            }},
        ]}},
    }


class EmergencyPlanCheckTest(unittest.TestCase):
    def run_tool(self, plan):
        with tempfile.TemporaryDirectory(prefix="entra-emergency-plan-test-") as temporary:
            path = Path(temporary) / "plan.json"
            path.write_text(json.dumps(plan))
            return subprocess.run([sys.executable, "-I", str(TOOL), str(path)],
                                  text=True, capture_output=True, check=False, timeout=5)

    def test_accepts_exact_creates_and_ignores_data_reads(self):
        result = self.run_tool(valid_plan())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Entra emergency administrator saved-plan check passed.\n")
        self.assertEqual(result.stderr, "")

    def test_rejects_unapproved_actions_and_redacts_plan_values(self):
        cases = {}

        extra = valid_plan()
        extra["resource_changes"].append(resource("azuread_group.unapproved", "azuread_group", {"secret": SECRET}, {}))
        cases["extra resource"] = extra

        no_op = valid_plan()
        no_op["resource_changes"][2]["change"]["actions"] = ["no-op"]
        cases["managed no-op"] = no_op

        replacement = valid_plan()
        replacement["resource_changes"][3]["change"]["actions"] = ["delete", "create"]
        cases["replacement"] = replacement

        imported = valid_plan()
        imported["resource_changes"][3]["change"]["importing"] = {"id": SECRET}
        cases["import"] = imported

        moved = valid_plan()
        moved["resource_changes"][4]["previous_address"] = "azuread_directory_role_assignment.old"
        cases["move"] = moved

        prior_state = valid_plan()
        prior_state["resource_changes"][2]["change"]["before"] = {"result": SECRET}
        cases["prior state"] = prior_state

        invalid_upn = valid_plan()
        invalid_upn["resource_changes"][3]["change"]["after"]["user_principal_name"] = SECRET
        cases["user principal name"] = invalid_upn

        invalid_role = valid_plan()
        invalid_role["resource_changes"][4]["change"]["after"]["role_id"] = SECRET
        cases["role template"] = invalid_role

        invalid_scope = valid_plan()
        invalid_scope["resource_changes"][4]["change"]["after"]["directory_scope_id"] = SECRET
        cases["directory scope"] = invalid_scope

        wrong_identity = valid_plan()
        wrong_identity["resource_changes"][3]["change"]["after"]["user_principal_name"] = "unreviewed-admin@example.onmicrosoft.com"
        cases["recovery account local part"] = wrong_identity

        foreign_principal = valid_plan()
        foreign_principal["resource_changes"][4]["change"]["after"]["principal_object_id"] = "00000000-0000-0000-0000-000000000001"
        cases["foreign role principal"] = foreign_principal

        disabled_account = valid_plan()
        disabled_account["resource_changes"][3]["change"]["after"]["account_enabled"] = False
        cases["disabled account"] = disabled_account

        expiring_password = valid_plan()
        expiring_password["resource_changes"][3]["change"]["after"]["disable_password_expiration"] = False
        cases["password expiration"] = expiring_password

        weak_password = valid_plan()
        weak_password["resource_changes"][2]["change"]["after"]["length"] = 12
        cases["weak password"] = weak_password

        detached_reference = valid_plan()
        detached_reference["configuration"]["root_module"]["resources"][2]["expressions"]["principal_object_id"] = {
            "references": ["azuread_group.other.object_id", "azuread_group.other"],
        }
        cases["detached role assignment"] = detached_reference

        wrong_domain = valid_plan()
        wrong_domain["resource_changes"][3]["change"]["after"]["user_principal_name"] = "homelab-emergency-admin@other.onmicrosoft.com"
        cases["wrong initial domain"] = wrong_domain

        multiple_initial_domains = valid_plan()
        multiple_initial_domains["resource_changes"][0]["change"]["after"]["domains"].append({
            "domain_name": "other.onmicrosoft.com", "initial": True, "verified": True,
            "authentication_type": "Managed",
        })
        cases["multiple initial domains"] = multiple_initial_domains

        literal_password = valid_plan()
        literal_password["resource_changes"][3]["change"]["after"]["password"] = SECRET
        cases["literal password"] = literal_password

        for name, plan in cases.items():
            with self.subTest(name=name):
                result = self.run_tool(copy.deepcopy(plan))
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("saved-plan check failed", result.stderr)
                self.assertNotIn(SECRET, result.stderr)


if __name__ == "__main__":
    unittest.main()
