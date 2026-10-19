#!/usr/bin/env python3
"""Offline failure fixtures for the pinned Enterprise API contract."""

import importlib.util
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("oce_reconciler", ROOT / "scripts/openclaw-enterprise.py")
OCE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = OCE
SPEC.loader.exec_module(OCE)


class FakeAPI:
    def __init__(self, reads):
        self.reads = reads
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path))
        return self.reads[path]

    def post(self, path, body):
        self.calls.append(("POST", path, body))
        raise AssertionError("offline fixture must not mutate")

    def patch(self, path, body):
        self.calls.append(("PATCH", path, body))
        raise AssertionError("offline fixture must not mutate")


class EnterpriseReconciliation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oce-reconciler-", dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name) / "private"
        self.private.mkdir(mode=0o700)
        self.config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        self.config["privateJournal"]["mountPath"] = str(self.private / "journal.json")

    def test_installation_read_cannot_prove_selected_drivers(self):
        installation = {"id": "ins_one", "name": "oce", "createdAt": "2026-10-18T00:00:00Z",
                        "capabilities": {"openclaw": {"executionModes": ["embedded"]}}}
        with self.assertRaisesRegex(OCE.Blocked, "selected Drivers"):
            OCE.require_driver_identity(installation)

    def test_service_key_rejects_header_injection(self):
        with self.assertRaisesRegex(OCE.Blocked, "service key is invalid"):
            OCE.API("https://console.oce.stinkyboi.com", "test-key\nother-header: injected")

    def test_check_and_reconcile_stop_before_mutation_on_driver_gap(self):
        api = FakeAPI({"/installation": {"id": "ins_one", "name": "oce",
                                         "capabilities": {"openclaw": {"executionModes": ["embedded"]}}}})
        with self.assertRaisesRegex(OCE.Blocked, "selected Drivers"):
            OCE.check(self.config, api)
        with self.assertRaisesRegex(OCE.Blocked, "selected Drivers"):
            OCE.reconcile(self.config, api, self.config["source"]["revision"])
        with self.assertRaisesRegex(OCE.Blocked, "selected Drivers"):
            OCE.verify(self.config, api)
        self.assertEqual(api.calls, [("GET", "/installation")] * 3)
        self.assertFalse((self.private / "journal.json").exists())

    def test_activation_requires_explicit_model_and_distinct_key_reference(self):
        active = {**self.config, "activationEnabled": True}
        with self.assertRaisesRegex(OCE.Blocked, "explicit model"):
            OCE._validate_config(active)
        active["model"] = {"provider": "openrouter", "id": "openrouter/free"}
        active["secrets"] = {**self.config["secrets"],
                             "modelApiKey": "/homelab/litellm/openrouter-api-key"}
        with self.assertRaisesRegex(OCE.Blocked, "dedicated key"):
            OCE._validate_config(active)
        active["secrets"]["modelApiKey"] = "/homelab/openclaw-enterprise/model-api-key"
        OCE._validate_config(active)

    def test_legacy_retention_data_is_not_read_or_imported(self):
        class UnreadableLegacy(dict):
            def get(self, *_args):
                raise AssertionError("legacy data was read")

        config = {**self.config, "legacyRetention": UnreadableLegacy()}
        api = FakeAPI({"/installation": {"id": "ins_one"}})
        with self.assertRaisesRegex(OCE.Blocked, "selected Drivers"):
            OCE.reconcile(config, api, self.config["source"]["revision"])
        self.assertEqual(api.calls, [("GET", "/installation")])

    def test_duplicate_or_unjournaled_logical_identity_is_foreign(self):
        owned = {"id": "ns_one", "name": "claw", "existingNamespace": "openclaw-agents"}
        with self.assertRaisesRegex(OCE.Blocked, "duplicate"):
            OCE.discover_exact([owned, {**owned, "id": "ns_two"}], "claw", "ns_one")
        with self.assertRaisesRegex(OCE.Blocked, "unjournaled"):
            OCE.discover_exact([owned], "claw", None)
        with self.assertRaisesRegex(OCE.Blocked, "changed identity"):
            OCE.discover_exact([{**owned, "existingNamespace": "other"}], "claw", "ns_one",
                               {"existingNamespace": "openclaw-agents"})
        self.assertEqual(OCE.discover_exact([owned], "claw", "ns_one",
                                            {"existingNamespace": "openclaw-agents"}), owned)

    def test_configuration_lost_response_requires_exact_owned_evidence_and_api_read(self):
        values = {"agents": {"defaults": {"model": "openrouter/free"}}}
        candidate = {
            "metadata": {"name": OCE.configuration_configmap_name("cfg_one"),
                         "namespace": "openclaw-agents",
                         "labels": {"app.kubernetes.io/managed-by": "openclaw-enterprise",
                                    "openclaw.dev/namespace": "ns_one",
                                    "openclaw.dev/configuration": "cfg_one"},
                         "annotations": {"openclaw.dev/namespace-id": "ns_one",
                                         "openclaw.dev/configuration-id": "cfg_one",
                                         "openclaw.dev/configuration-kind": "agent",
                                         "openclaw.dev/configuration-generation": "1",
                                         "openclaw.dev/configuration-created-at": "2026-10-18T00:00:00Z"}},
            "data": {"openclaw.json": json.dumps(values)},
        }
        exact = {"id": "cfg_one", "namespaceId": "ns_one", "kind": "agent",
                 "generation": 1, "values": values,
                 "createdAt": "2026-10-18T00:00:00Z"}
        with self.assertRaisesRegex(OCE.Blocked, "ambiguous"):
            OCE.recover_configuration([candidate, candidate], exact, "openclaw-agents")
        with self.assertRaisesRegex(OCE.Blocked, "foreign"):
            OCE.recover_configuration([{**candidate, "metadata": {
                **candidate["metadata"], "labels": {**candidate["metadata"]["labels"],
                                                  "openclaw.dev/namespace": "ns_other"}}}],
                exact, "openclaw-agents")
        self.assertEqual(OCE.recover_configuration([candidate], exact, "openclaw-agents"),
                         "cfg_one")

    def test_generation_conflict_is_not_silently_rebased(self):
        current = {"id": "cfg_one", "namespaceId": "ns_one", "generation": 3,
                   "values": {"agents": {"defaults": {"model": "old"}}}}
        with self.assertRaisesRegex(OCE.Blocked, "generation"):
            OCE.configuration_patch(current, {"agents": {"defaults": {"model": "new"}}}, 2)
        self.assertEqual(OCE.configuration_patch(current, {"agents": {"defaults": {
            "model": "new"}}}, 3)["expectedGeneration"], 3)

    def test_ambiguous_deploy_response_never_causes_second_deploy(self):
        baseline = {"rev_old"}
        matching = {"id": "rev_new", "agentId": "agt_one", "namespaceId": "ns_one",
                    "configurationId": "cfg_one", "configurationGeneration": 2}
        with self.assertRaisesRegex(OCE.Blocked, "unknown"):
            OCE.recover_revision([], baseline, "agt_one", "cfg_one", 2)
        with self.assertRaisesRegex(OCE.Blocked, "ambiguous"):
            OCE.recover_revision([matching, {**matching, "id": "rev_newer"}], baseline,
                                 "agt_one", "cfg_one", 2)
        self.assertEqual(OCE.recover_revision([matching], baseline, "agt_one", "cfg_one", 2),
                         "rev_new")

    def test_worker_restart_and_repeated_reconcile_do_not_redeploy(self):
        agent = {"id": "agt_one", "namespaceId": "ns_one", "status": "active",
                 "configurationId": "cfg_one", "desiredRuntimeState": "running",
                 "activeRevisionId": "rev_one"}
        revision = {"id": "rev_one", "agentId": "agt_one",
                    "configurationId": "cfg_one", "configurationGeneration": 2}
        status = {"deploymentId": "rev_one", "namespaceId": "ns_one",
                  "agentId": "agt_one", "status": "succeeded"}
        self.assertFalse(OCE.should_deploy(agent, revision, status, "cfg_one", 2))
        with self.assertRaisesRegex(OCE.Blocked, "in progress"):
            OCE.should_deploy(agent, revision, {**status, "status": "running"}, "cfg_one", 2)
        with self.assertRaisesRegex(OCE.Blocked, "failed"):
            OCE.should_deploy(agent, revision, {**status, "status": "failed"}, "cfg_one", 2)
        self.assertTrue(OCE.should_deploy(agent, revision, status, "cfg_one", 3))
        with self.assertRaisesRegex(OCE.Blocked, "identity"):
            OCE.should_deploy({**agent, "activeRevisionId": "rev_other"}, revision,
                              status, "cfg_one", 3)

    def test_revoked_or_partial_model_grant_blocks_deployment(self):
        role = {"id": "role_one", "namespaceId": "ns_one",
                "permissions": [{"action": "operate", "resourceKind": "secret"}]}
        binding = {"id": "binding_one", "namespaceId": "ns_one",
                   "subjectKind": "identity", "subjectId": "sp_one", "roleId": "role_one",
                   "resourceKind": "secret", "resourceId": "sec_one"}
        self.assertEqual(OCE.exact_model_grant([role], [binding], "ns_one", "sp_one", "sec_one"),
                         ("role_one", "binding_one"))
        with self.assertRaisesRegex(OCE.Blocked, "grant"):
            OCE.exact_model_grant([role], [], "ns_one", "sp_one", "sec_one")
        with self.assertRaisesRegex(OCE.Blocked, "grant"):
            OCE.exact_model_grant([role], [{**binding, "resourceId": "sec_other"}],
                                  "ns_one", "sp_one", "sec_one")

    def test_protected_journal_rejects_permissions_symlinks_and_changed_source(self):
        path = self.private / "journal.json"
        with OCE.ProtectedJournal(path, "a" * 40, "b" * 64) as journal:
            with self.assertRaisesRegex(OCE.Blocked, "identity"):
                journal.save({"namespaceId": "sk-sensitive-value"})
            with self.assertRaisesRegex(OCE.Blocked, "desired hash"):
                journal.save({"desiredHash": {"apiKey": "do-not-store"}})
            journal.save({"namespaceId": "ns_one"})
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with self.assertRaisesRegex(OCE.Blocked, "source"):
            with OCE.ProtectedJournal(path, "c" * 40, "b" * 64):
                pass
        with self.assertRaisesRegex(OCE.Blocked, "source"):
            with OCE.ProtectedJournal(path, "a" * 40, "c" * 64):
                pass
        path.chmod(0o644)
        with self.assertRaisesRegex(OCE.Blocked, "mode"):
            with OCE.ProtectedJournal(path, "a" * 40, "b" * 64):
                pass
        path.unlink()
        path.symlink_to(self.private / "other")
        with self.assertRaisesRegex(OCE.Blocked, "symlink"):
            with OCE.ProtectedJournal(path, "a" * 40, "b" * 64):
                pass


if __name__ == "__main__":
    unittest.main()
