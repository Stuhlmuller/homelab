#!/usr/bin/env python3
"""Offline checks for the guarded, read-only Entra owner conversion transaction."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "entra-owner-conversion.py"
SPEC = importlib.util.spec_from_file_location("entra_owner_conversion", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SHA = "a" * 40
FUTURE_PASSWORD_CHANGE = "9999-12-31T23:59:59Z"
RECOVERY_OBJECT_ID = "2c1bc8ba-02ea-4dac-8b1a-88d33bfbac91"


class Response:
    status = 200

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return json.dumps(self.value).encode()


def prepared_state():
    return {
        "owner": {"id": MODULE.OWNER_OBJECT_ID, "userPrincipalName": MODULE.OWNER_UPN,
                  "userType": "Member", "creationType": "Invitation",
                  "externalUserState": "Accepted", "accountEnabled": True},
        "domain": {"id": MODULE.TARGET_DOMAIN, "isVerified": True,
                   "authenticationType": "Managed", "isDefault": False, "isInitial": False},
        "default_domain": {"id": "stinkyboi.com", "isVerified": True, "isDefault": True},
        "target": None,
        "recovery": recovery_state(),
    }


def recovery_state():
    initial_domain = {
        "id": "stinkyboi.onmicrosoft.com", "isVerified": True,
        "authenticationType": "Managed", "isDefault": False, "isInitial": True,
    }
    actor = {
        "id": RECOVERY_OBJECT_ID,
        "userPrincipalName": f"{MODULE.EMERGENCY_ADMIN_LOCAL_PART}@{initial_domain['id']}",
        "userType": "Member", "accountEnabled": True,
        "onPremisesSyncEnabled": None, "externalUserState": None,
    }
    return {
        "initial_domain": initial_domain,
        "actor": actor,
        "assignment": {"value": [{
            "id": "global-administrator-assignment",
            "principalId": RECOVERY_OBJECT_ID,
            "roleDefinitionId": MODULE.GLOBAL_ADMINISTRATOR_ROLE_DEFINITION_ID,
            "directoryScopeId": "/",
            "appScopeId": None,
        }]},
    }


def attested_state():
    return {
        "owner": {"id": MODULE.OWNER_OBJECT_ID, "userPrincipalName": MODULE.TARGET_UPN,
                  "userType": "Member", "externalUserState": None,
                  "identities": [{"signInType": "userPrincipalName",
                                  "issuer": "stinkyboi.com",
                                  "issuerAssignedId": MODULE.TARGET_UPN}],
                  "onPremisesSyncEnabled": None,
                  "lastPasswordChangeDateTime": FUTURE_PASSWORD_CHANGE,
                  "accountEnabled": True},
        "domain": {"id": MODULE.TARGET_DOMAIN, "isVerified": True,
                   "authenticationType": "Managed", "isDefault": False, "isInitial": False},
        "default_domain": {"id": "stinkyboi.com", "isVerified": True, "isDefault": True},
        "target": {"id": MODULE.OWNER_OBJECT_ID},
        "actor": {"id": MODULE.OWNER_OBJECT_ID, "userPrincipalName": MODULE.TARGET_UPN},
        "recovery": recovery_state(),
    }


class ConversionTransactionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "receipt"
        self.directory.mkdir(mode=0o700)
        self.directory.chmod(0o700)

    def run_command(self, action, state, *, sha=SHA, directory=None):
        output = io.StringIO()
        argv = [action, "--expected-sha", sha, "--receipt-directory", str(directory or self.directory)]
        with patch.object(MODULE, "verify_main", return_value=SHA) as verified, \
                patch.object(MODULE, "graph_state", return_value=state), \
                redirect_stdout(output), redirect_stderr(output):
            status = MODULE.main(argv)
        for private in (MODULE.OWNER_UPN,):
            self.assertNotIn(private, output.getvalue())
        return status, output.getvalue(), verified

    def receipt(self):
        path = self.directory / MODULE.RECEIPT_NAME
        self.assertTrue(path.exists())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        return path, json.loads(path.read_text())

    def test_prepare_creates_private_read_only_transaction(self):
        status, output, verified = self.run_command("prepare", prepared_state())
        self.assertEqual(status, 0, output)
        path, receipt = self.receipt()
        self.assertEqual(path.parent, self.directory)
        self.assertEqual(receipt["schema"], 5)
        self.assertEqual(receipt["status"], "prepared")
        self.assertEqual(receipt["expected_sha"], SHA)
        self.assertEqual(receipt["owner_object_id"], MODULE.OWNER_OBJECT_ID)
        self.assertEqual(receipt["target_upn"], MODULE.TARGET_UPN)
        self.assertEqual(receipt["before"]["userType"], "Member")
        self.assertEqual(receipt["before"]["creationType"], "Invitation")
        self.assertEqual(receipt["default_domain"]["id"], "stinkyboi.com")
        self.assertEqual(receipt["recovery"]["actor"]["id"], RECOVERY_OBJECT_ID)
        self.assertEqual(receipt["recovery"]["assignment"]["directoryScopeId"], "/")
        self.assertEqual(verified.call_count, 2)
        self.assertIn("No Graph write was made", output)

    def test_prepare_refuses_replay_or_occupied_target(self):
        self.assertEqual(self.run_command("prepare", prepared_state())[0], 0)
        status, output, _ = self.run_command("prepare", prepared_state())
        self.assertEqual(status, 1)
        self.assertIn("already exists", output)
        other = Path(self.temporary.name) / "other"
        other.mkdir(mode=0o700)
        other.chmod(0o700)
        occupied = prepared_state()
        occupied["target"] = {"id": "different"}
        status, output, _ = self.run_command("prepare", occupied, directory=other)
        self.assertEqual(status, 1)
        self.assertIn("already occupied", output)
        self.assertFalse((other / MODULE.RECEIPT_NAME).exists())

    def test_prepare_requires_the_known_external_member_baseline(self):
        cases = []
        guest = prepared_state()
        guest["owner"]["userType"] = "Guest"
        cases.append(guest)
        local = prepared_state()
        local["owner"]["creationType"] = "LocalAccount"
        cases.append(local)
        pending = prepared_state()
        pending["owner"]["externalUserState"] = "PendingAcceptance"
        cases.append(pending)
        wrong_upn = prepared_state()
        wrong_upn["owner"]["userPrincipalName"] = "other@example.test"
        cases.append(wrong_upn)
        for state in cases:
            with self.subTest(state=state["owner"]):
                directory = Path(self.temporary.name) / f"receipt-{len(list(Path(self.temporary.name).glob('receipt-*')))}"
                directory.mkdir(mode=0o700)
                directory.chmod(0o700)
                status, output, _ = self.run_command("prepare", state, directory=directory)
                self.assertEqual(status, 1)
                self.assertIn("does not match", output)

    def test_prepare_requires_an_authenticated_independent_recovery_global_administrator(self):
        cases = []
        missing = prepared_state()
        missing.pop("recovery")
        cases.append(missing)
        wrong_actor = prepared_state()
        wrong_actor["recovery"]["actor"]["userPrincipalName"] = MODULE.OWNER_UPN
        cases.append(wrong_actor)
        disabled = prepared_state()
        disabled["recovery"]["actor"]["accountEnabled"] = False
        cases.append(disabled)
        synced = prepared_state()
        synced["recovery"]["actor"]["onPremisesSyncEnabled"] = True
        cases.append(synced)
        external = prepared_state()
        external["recovery"]["actor"]["externalUserState"] = "Accepted"
        cases.append(external)
        invalid_initial_domain = prepared_state()
        invalid_initial_domain["recovery"]["initial_domain"]["isInitial"] = False
        cases.append(invalid_initial_domain)
        wrong_assignment = prepared_state()
        wrong_assignment["recovery"]["assignment"]["value"][0]["roleDefinitionId"] = "other"
        cases.append(wrong_assignment)
        missing_assignment = prepared_state()
        missing_assignment["recovery"]["assignment"] = {"value": []}
        cases.append(missing_assignment)
        scoped_assignment = prepared_state()
        scoped_assignment["recovery"]["assignment"]["value"][0]["directoryScopeId"] = "/applications/other"
        cases.append(scoped_assignment)
        app_scoped_assignment = prepared_state()
        app_scoped_assignment["recovery"]["assignment"]["value"][0]["appScopeId"] = "/appScope"
        cases.append(app_scoped_assignment)
        paged_assignment = prepared_state()
        paged_assignment["recovery"]["assignment"]["@odata.nextLink"] = "https://graph.microsoft.com/v1.0/next"
        cases.append(paged_assignment)
        for index, state in enumerate(cases):
            with self.subTest(index=index):
                directory = Path(self.temporary.name) / f"recovery-{index}"
                directory.mkdir(mode=0o700)
                directory.chmod(0o700)
                status, output, _ = self.run_command("prepare", state, directory=directory)
                self.assertEqual(status, 1)
                self.assertIn("recovery administrator", output)
                self.assertFalse((directory / MODULE.RECEIPT_NAME).exists())

    def test_initial_recovery_domain_must_be_unique(self):
        initial = recovery_state()["initial_domain"]
        with self.assertRaises(MODULE.Failure):
            MODULE.initial_domain_state({"value": []})
        with self.assertRaises(MODULE.Failure):
            MODULE.initial_domain_state({"value": [initial, initial]})

    def test_attest_requires_internal_postcondition_and_preserves_ambiguous_receipt(self):
        self.assertEqual(self.run_command("prepare", prepared_state())[0], 0)
        path, before = self.receipt()
        ambiguous = prepared_state()
        ambiguous["owner"]["userType"] = "Member"
        status, output, _ = self.run_command("attest", ambiguous)
        self.assertEqual(status, 1)
        self.assertIn("does not match", output)
        self.assertEqual(json.loads(path.read_text()), before)
        invalid_states = []
        external = attested_state()
        external["owner"]["creationType"] = "Invitation"
        external["owner"]["externalUserState"] = "Accepted"
        invalid_states.append(external)
        missing = attested_state()
        del missing["owner"]["externalUserState"]
        invalid_states.append(missing)
        external_identity = attested_state()
        external_identity["owner"]["identities"] = [{"signInType": "federated",
                                                        "issuer": "ExternalAzureAD",
                                                        "issuerAssignedId": "private"}]
        invalid_states.append(external_identity)
        multiple_identities = attested_state()
        multiple_identities["owner"]["identities"].append({"signInType": "federated",
                                                               "issuer": "ExternalAzureAD",
                                                               "issuerAssignedId": "private"})
        invalid_states.append(multiple_identities)
        formerly_synced = attested_state()
        formerly_synced["owner"]["onPremisesSyncEnabled"] = False
        invalid_states.append(formerly_synced)
        synced = attested_state()
        synced["owner"]["onPremisesSyncEnabled"] = True
        invalid_states.append(synced)
        missing_sync_state = attested_state()
        del missing_sync_state["owner"]["onPremisesSyncEnabled"]
        invalid_states.append(missing_sync_state)
        changed_default_domain = attested_state()
        changed_default_domain["default_domain"] = {
            "id": "different.example.test", "isVerified": True, "isDefault": True,
        }
        invalid_states.append(changed_default_domain)
        stale_password = attested_state()
        stale_password["owner"]["lastPasswordChangeDateTime"] = "1970-01-01T00:00:00Z"
        invalid_states.append(stale_password)
        wrong_actor = attested_state()
        wrong_actor["actor"]["id"] = "other"
        invalid_states.append(wrong_actor)
        for state in invalid_states:
            with self.subTest(state=state):
                status, output, _ = self.run_command("attest", state)
                self.assertEqual(status, 1)
                self.assertIn("does not match", output)
                self.assertEqual(json.loads(path.read_text()), before)
        status, output, _ = self.run_command("attest", attested_state())
        self.assertEqual(status, 0, output)
        _, receipt = self.receipt()
        self.assertEqual(receipt["status"], "attested")
        self.assertEqual(receipt["after"]["id"], MODULE.OWNER_OBJECT_ID)
        self.assertEqual(receipt["after"]["userPrincipalName"], MODULE.TARGET_UPN)
        self.assertIsNone(receipt["after"]["externalUserState"])
        self.assertIsNone(receipt["after"]["onPremisesSyncEnabled"])
        self.assertEqual(receipt["after"]["identities"][0]["issuer"], "stinkyboi.com")
        self.assertEqual(self.run_command("attest", attested_state())[0], 0)

    def test_attest_rechecks_the_same_independent_recovery_assignment(self):
        self.assertEqual(self.run_command("prepare", prepared_state())[0], 0)
        path, before = self.receipt()
        cases = []
        removed = attested_state()
        removed["recovery"]["assignment"] = {"value": []}
        cases.append(removed)
        wrong_actor = attested_state()
        wrong_actor["recovery"]["assignment"]["value"][0]["principalId"] = "different"
        cases.append(wrong_actor)
        changed_assignment = attested_state()
        changed_assignment["recovery"]["assignment"]["value"][0]["id"] = "recreated"
        cases.append(changed_assignment)
        for state in cases:
            with self.subTest(state=state["recovery"]):
                status, output, _ = self.run_command("attest", state)
                self.assertEqual(status, 1)
                self.assertIn("recovery administrator", output)
                self.assertEqual(json.loads(path.read_text()), before)

    def test_attest_requires_a_strictly_later_password_timestamp(self):
        prepared_at = "2030-01-01T00:00:00.900000Z"
        with patch.object(MODULE, "timestamp", return_value=prepared_at):
            self.assertEqual(self.run_command("prepare", prepared_state())[0], 0)
        same_second = attested_state()
        same_second["owner"]["lastPasswordChangeDateTime"] = "2030-01-01T00:00:00Z"
        status, output, _ = self.run_command("attest", same_second)
        self.assertEqual(status, 1)
        self.assertIn("does not match", output)
        equal = attested_state()
        equal["owner"]["lastPasswordChangeDateTime"] = prepared_at
        self.assertEqual(self.run_command("attest", equal)[0], 1)
        later = attested_state()
        later["owner"]["lastPasswordChangeDateTime"] = "2030-01-01T00:00:01Z"
        self.assertEqual(self.run_command("attest", later)[0], 0)

    def test_timestamp_preserves_microseconds(self):
        instant = MODULE.datetime(2030, 1, 1, 0, 0, 0, 900000, tzinfo=MODULE.timezone.utc)
        with patch.object(MODULE, "datetime") as clock:
            clock.now.return_value = instant
            self.assertEqual(MODULE.timestamp(), "2030-01-01T00:00:00.900000Z")

    def test_attest_refuses_a_tampered_external_postcondition_receipt(self):
        self.assertEqual(self.run_command("prepare", prepared_state())[0], 0)
        self.assertEqual(self.run_command("attest", attested_state())[0], 0)
        path, receipt = self.receipt()
        receipt["after"]["externalUserState"] = "Accepted"
        path.write_text(json.dumps(receipt))
        status, output, _ = self.run_command("attest", attested_state())
        self.assertEqual(status, 1)
        self.assertIn("does not match", output)
        self.assertEqual(json.loads(path.read_text()), receipt)

    def test_attest_refuses_a_tampered_preflight_receipt(self):
        self.assertEqual(self.run_command("prepare", prepared_state())[0], 0)
        path, receipt = self.receipt()
        receipt["before"] = {}
        path.write_text(json.dumps(receipt))
        status, output, _ = self.run_command("attest", attested_state())
        self.assertEqual(status, 1)
        self.assertIn("does not match", output)
        self.assertEqual(json.loads(path.read_text()), receipt)

    def test_receipt_directory_and_file_must_be_private_non_symlink_paths(self):
        insecure = Path(self.temporary.name) / "insecure"
        insecure.mkdir(mode=0o755)
        insecure.chmod(0o755)
        status, output, _ = self.run_command("prepare", prepared_state(), directory=insecure)
        self.assertEqual(status, 1)
        self.assertIn("mode 0700", output)
        link = Path(self.temporary.name) / "link"
        os.symlink(self.directory, link)
        status, output, _ = self.run_command("prepare", prepared_state(), directory=link)
        self.assertEqual(status, 1)
        self.assertIn("must not be a symlink", output)
        nested = self.directory / "inside-git"
        nested.mkdir(mode=0o700)
        nested.chmod(0o700)
        with patch.object(MODULE, "ROOT", self.directory.resolve()), self.assertRaises(MODULE.Failure):
            MODULE.private_directory(nested)
        self.assertEqual(self.run_command("prepare", prepared_state())[0], 0)
        receipt = self.directory / MODULE.RECEIPT_NAME
        receipt.unlink()
        os.symlink(Path(self.temporary.name) / "other", receipt)
        status, output, _ = self.run_command("attest", attested_state())
        self.assertEqual(status, 1)
        self.assertIn("mode 0600 regular file", output)

    def test_expected_sha_must_be_exact_current_signed_main(self):
        with self.assertRaises(MODULE.Failure):
            MODULE.verify_main("not-a-sha")

    def test_signed_main_gate_rejects_dirty_or_stale_or_unverified_checkouts(self):
        cases = (
            ("clean", "", SHA, {"sha": SHA, "commit": {"verification": {"verified": True}}}, True),
            ("dirty", " M private", SHA, {"sha": SHA, "commit": {"verification": {"verified": True}}}, False),
            ("head mismatch", "", "b" * 40, {"sha": "b" * 40, "commit": {"verification": {"verified": True}}}, False),
            ("remote mismatch", "", SHA, {"sha": "b" * 40, "commit": {"verification": {"verified": True}}}, False),
            ("unverified", "", SHA, {"sha": SHA, "commit": {"verification": {"verified": False}}}, False),
        )
        for label, status, head, remote, succeeds in cases:
            with self.subTest(label=label), \
                    patch.object(MODULE, "command", side_effect=(status, head + "\n")), \
                    patch.object(MODULE, "github", return_value=remote) as github:
                if succeeds:
                    self.assertEqual(MODULE.verify_main(SHA), SHA)
                else:
                    with self.assertRaises(MODULE.Failure):
                        MODULE.verify_main(SHA)
                if label == "dirty":
                    github.assert_not_called()

    def test_graph_calls_use_only_v1_get_requests(self):
        response = Response({"id": MODULE.OWNER_OBJECT_ID})
        opener = MagicMock(return_value=response)
        with patch.object(MODULE.GRAPH_OPENER, "open", opener):
            self.assertEqual(MODULE.graph_get("private-token", "users/example"),
                             {"id": MODULE.OWNER_OBJECT_ID})
        request = opener.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertTrue(request.full_url.startswith("https://graph.microsoft.com/v1.0/users/example"))
        self.assertNotIn("beta", request.full_url)
        self.assertIsNone(request.data)

    def test_recovery_assignment_read_is_a_direct_root_role_query(self):
        response = Response({"value": []})
        opener = MagicMock(return_value=response)
        with patch.object(MODULE.GRAPH_OPENER, "open", opener):
            MODULE.graph_get("private-token", MODULE.emergency_role_assignment_path(RECOVERY_OBJECT_ID))
        request = opener.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertTrue(request.full_url.startswith("https://graph.microsoft.com/v1.0/"))
        self.assertIn("roleManagement/directory/roleAssignments?", request.full_url)
        self.assertIn("principalId", request.full_url)
        self.assertIn("roleDefinitionId", request.full_url)
        self.assertIn("directoryScopeId", request.full_url)
        self.assertNotIn("memberOf", request.full_url)
        self.assertNotIn("%24count", request.full_url)
        self.assertIsNone(request.get_header("Consistencylevel"))
        self.assertIsNone(request.data)

    def test_graph_state_selects_local_identity_and_reads_actor_only_for_attestation(self):
        recovery = recovery_state()
        default_domains = {"value": [prepared_state()["default_domain"], recovery["initial_domain"]]}
        values = {
            f"users/{MODULE.OWNER_OBJECT_ID}?$select=id,userPrincipalName,userType,creationType,externalUserState,accountEnabled,identities,onPremisesSyncEnabled,lastPasswordChangeDateTime": attested_state()["owner"],
            f"domains/{MODULE.TARGET_DOMAIN}": attested_state()["domain"],
            "domains?$select=id,isVerified,authenticationType,isDefault,isInitial": default_domains,
            f"users/{MODULE.TARGET_UPN}?$select=id": attested_state()["target"],
            "me?$select=id,userPrincipalName": attested_state()["actor"],
            "me?$select=id,userPrincipalName,userType,accountEnabled,onPremisesSyncEnabled,externalUserState": recovery["actor"],
            f"users/{RECOVERY_OBJECT_ID}?$select=id,userPrincipalName,userType,accountEnabled,onPremisesSyncEnabled,externalUserState": recovery["actor"],
            MODULE.emergency_role_assignment_path(RECOVERY_OBJECT_ID): recovery["assignment"],
        }
        calls = []

        def get(_token, path, **kwargs):
            calls.append((path, kwargs))
            return values[path]

        with patch.object(MODULE, "graph_token", return_value="private-token"), \
                patch.object(MODULE, "graph_get", side_effect=get):
            self.assertNotIn("actor", MODULE.graph_state())
            self.assertEqual(MODULE.graph_state(include_actor=True)["actor"], attested_state()["actor"])
            self.assertEqual(MODULE.graph_state(recovery_actor_id="")["recovery"]["actor"], recovery["actor"])
            self.assertEqual(MODULE.graph_state(recovery_actor_id=RECOVERY_OBJECT_ID)["recovery"]["actor"], recovery["actor"])
        self.assertEqual(calls.count(("me?$select=id,userPrincipalName", {})), 1)
        self.assertEqual(calls.count((
            "me?$select=id,userPrincipalName,userType,accountEnabled,onPremisesSyncEnabled,externalUserState", {}
        )), 1)
        self.assertIn((
            f"users/{RECOVERY_OBJECT_ID}?$select=id,userPrincipalName,userType,accountEnabled,onPremisesSyncEnabled,externalUserState", {}
        ), calls)
        self.assertIn((MODULE.emergency_role_assignment_path(RECOVERY_OBJECT_ID), {}), calls)
        self.assertIn((f"users/{MODULE.TARGET_UPN}?$select=id", {"missing": True}), calls)

    def test_graph_redirect_is_rejected_before_token_forwarding(self):
        with self.assertRaises(MODULE.Failure):
            MODULE.RejectRedirects().redirect_request(None, None, 302, "Found", None,
                                                       "https://example.invalid/")

    def test_graph_opener_ignores_environment_proxies(self):
        with patch.object(MODULE.urllib.request, "getproxies",
                          return_value={"https": "http://proxy.invalid:8080"}):
            isolated_spec = importlib.util.spec_from_file_location("isolated_conversion", SCRIPT)
            isolated = importlib.util.module_from_spec(isolated_spec)
            isolated_spec.loader.exec_module(isolated)
        self.assertFalse(any(isinstance(handler, MODULE.urllib.request.ProxyHandler)
                             for handler in isolated.GRAPH_OPENER.handlers))


if __name__ == "__main__":
    unittest.main()
