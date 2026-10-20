#!/usr/bin/env python3
"""Offline state-machine fixtures for the gated Enterprise active lifecycle."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "oce_base_fixtures", ROOT / "scripts/ci/openclaw-enterprise-test.py")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
OCE = BASE.OCE


class ActiveAgentReconciliation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oce-active-")
        self.addCleanup(self.temp.cleanup)
        private = Path(self.temp.name).resolve() / "private"
        private.mkdir(mode=0o700)
        self.config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        self.config["privateJournal"]["mountPath"] = str(private / "journal.json")
        self.api = BASE.ActiveTenantAPI()
        self.kube = BASE.TenantKubernetes(self.api)
        self.credential = {"version": 1, "key": "new-openrouter-key-only"}
        with OCE.ProtectedJournal(private / "journal.json", self.config["source"]["revision"],
                                  OCE._identity_hash(self.config)) as journal:
            journal.save({"installationId": "ins_one", "namespaceId": "ns_one"})
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}):
            OCE.reconcile(self.config, self.api, self.kube, "a" * 40)
        self.config["activationEnabled"] = True

    def _active(self):
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}):
            return OCE.reconcile(self.config, self.api, self.kube, "a" * 40,
                                 self.credential)

    def _verify(self):
        with patch.object(OCE, "check", return_value={"installationId": "ins_one"}):
            return OCE.verify(self.config, self.api, self.kube)

    def _stop(self):
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}):
            return OCE.stop_agent(self.config, self.api, self.kube, "a" * 40)

    def _journal(self):
        return OCE.read_journal(self.config["privateJournal"]["mountPath"],
                                self.config["source"]["revision"],
                                OCE._identity_hash(self.config))[0]

    def test_active_repeat_verify_and_stop_are_idempotent(self):
        self.assertEqual(self._active()["revisionId"], "rev_one")
        writes = [call for call in self.api.calls if call[0].startswith("POST") or
                  call[0] == "PATCH"]
        self.assertEqual([call[1] for call in writes], [
            "/namespaces/ns_one/configurations", "/namespaces/ns_one/agents",
            "/namespaces/ns_one/secrets", "/namespaces/ns_one/iam/roles",
            "/namespaces/ns_one/iam/access-bindings", "/namespaces/ns_one/agents/agt_one",
            "/namespaces/ns_one/agents/agt_one/runtime-credentials",
            "/namespaces/ns_one/agents/agt_one/deploy"])
        self.assertEqual(self._active()["revisionId"], "rev_one")
        self.assertEqual(self._verify()["desiredRuntimeState"], "running")
        self.assertEqual([call for call in self.api.calls if call[0].startswith("POST") or
                          call[0] == "PATCH"], writes)
        self.assertEqual(self._stop()["desiredRuntimeState"], "stopped")
        self.assertEqual(self._stop()["desiredRuntimeState"], "stopped")
        self.assertEqual(self._verify()["desiredRuntimeState"], "stopped")
        self.assertEqual(len([call for call in self.api.calls if call[1].endswith("/stop")]), 1)
        self.assertEqual(self._journal()["revisionId"], "rev_one")
        self.assertNotIn("pending", self._journal())

    def test_active_gate_keeps_committed_config_off_and_needs_key(self):
        self.assertFalse(json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())[
            "activationEnabled"])
        with patch.object(OCE, "prove_driver_identity") as proof:
            with self.assertRaisesRegex(OCE.Blocked, "protected model credential"):
                OCE.reconcile(self.config, self.api, self.kube, "a" * 40)
        proof.assert_not_called()

    def test_placeholder_key_cannot_start_active_reconciliation(self):
        before = list(self.api.calls)
        with patch.object(OCE, "prove_driver_identity") as proof:
            with self.assertRaisesRegex(OCE.Blocked, "protected model credential"):
                OCE.reconcile(self.config, self.api, self.kube, "a" * 40,
                              {"version": 1, "key": "REPLACE_ME"})
        proof.assert_not_called()
        self.assertEqual(self.api.calls, before)

    def test_mutation_config_must_match_exact_committed_file(self):
        source = ROOT / "scripts/config/openclaw-enterprise.json"
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        OCE._require_reviewed_mutation_config(source, head)
        replacement = Path(self.temp.name) / "override.json"
        replacement.write_bytes(source.read_bytes())
        with self.assertRaisesRegex(OCE.Blocked, "not repository-owned"):
            OCE._require_reviewed_mutation_config(replacement, head)

    def test_model_credential_file_contract_and_permissions(self):
        parent = Path(self.temp.name).resolve() / "key"
        parent.mkdir(mode=0o700)
        path = parent / "model.json"
        path.write_text(json.dumps({"parameter": self.config["secrets"]["modelApiKey"],
                                    "version": 1, "key": "different-key"}))
        path.chmod(0o600)
        self.assertEqual(OCE._read_model_credential(path, self.config["secrets"]["modelApiKey"]),
                         {"version": 1, "key": "different-key"})
        path.chmod(0o644)
        with self.assertRaisesRegex(OCE.Blocked, "mode is unsafe"):
            OCE._read_model_credential(path, self.config["secrets"]["modelApiKey"])
        path.chmod(0o600)
        path.write_text(json.dumps({"parameter": "/wrong", "version": 1, "key": "test"}))
        with self.assertRaisesRegex(OCE.Blocked, "credential contract"):
            OCE._read_model_credential(path, self.config["secrets"]["modelApiKey"])

    def test_lost_secret_role_and_binding_creates_recover_without_repost(self):
        for operation, message in (("secret", "Secret"), ("role", "Role"),
                                   ("binding", "Binding")):
            self.api.lose = operation
            with self.assertRaisesRegex(OCE.Blocked, "lost " + message + " response"):
                self._active()
            self.assertEqual(self._journal()["pending"]["operation"],
                             operation + "-create" if operation != "binding" else "binding-create")
        self.assertEqual(self._active()["revisionId"], "rev_one")
        self.assertEqual(len(self.api.secrets), 1)
        self.assertEqual(len(self.api.roles), 1)
        self.assertEqual(len(self.api.bindings), 1)
        self.assertNotIn(self.credential["key"], repr(self.api.calls))

    def test_definitive_rejections_clear_only_proven_absent_create_intents(self):
        original_post = self.api.post
        for path, operation in (("/namespaces/ns_one/secrets", "secret-create"),
                                ("/namespaces/ns_one/iam/roles", "role-create"),
                                ("/namespaces/ns_one/iam/access-bindings", "binding-create")):
            def reject(selected, body):
                if selected == path:
                    raise OCE.DefinitiveRejection("HTTP 403")
                return original_post(selected, body)

            with patch.object(self.api, "post", side_effect=reject):
                with self.assertRaisesRegex(OCE.DefinitiveRejection, "HTTP 403"):
                    self._active()
            self.assertNotIn("pending", self._journal(), operation)
            if operation == "secret-create":
                self.assertNotIn("secretName", self._journal())
                self.assertNotIn("modelKeyVersion", self._journal())
        self.assertEqual(self._active()["revisionId"], "rev_one")

    def test_definitive_deploy_and_stop_rejection_need_absence_proof(self):
        original = self.api.post_accepted

        def reject_deploy(path, body=None):
            if path.endswith("/deploy"):
                raise OCE.DefinitiveRejection("HTTP 403")
            return original(path, body)

        with patch.object(self.api, "post_accepted", side_effect=reject_deploy):
            with self.assertRaisesRegex(OCE.DefinitiveRejection, "HTTP 403"):
                self._active()
        self.assertNotIn("pending", self._journal())
        self.assertEqual(self.api.revisions, {})
        self.assertEqual(self._active()["revisionId"], "rev_one")

        def reject_stop(path, body=None):
            if path.endswith("/stop"):
                raise OCE.DefinitiveRejection("HTTP 403")
            return original(path, body)

        with patch.object(self.api, "post_accepted", side_effect=reject_stop):
            with self.assertRaisesRegex(OCE.DefinitiveRejection, "HTTP 403"):
                self._stop()
        self.assertNotIn("pending", self._journal())
        self.assertEqual(self.api.agents["agt_one"]["desiredRuntimeState"], "running")
        self.assertEqual(self._stop()["desiredRuntimeState"], "stopped")

    def test_rejected_deploy_with_changed_agent_keeps_pending_intent(self):
        def reject_after_change(path, body=None):
            if path.endswith("/deploy"):
                self.api.agents["agt_one"]["desiredRuntimeState"] = "running"
                raise OCE.DefinitiveRejection("HTTP 403")
            raise AssertionError("unexpected accepted POST")

        with patch.object(self.api, "post_accepted", side_effect=reject_after_change):
            with self.assertRaisesRegex(OCE.Blocked, "Agent state changed"):
                self._active()
        self.assertEqual(self._journal()["pending"]["operation"], "deploy")

    def test_unknown_secret_create_without_readback_never_reposts(self):
        original_post = self.api.post

        def lose_before_create(path, body):
            if path == "/namespaces/ns_one/secrets":
                raise OCE.Blocked("lost Secret response")
            return original_post(path, body)

        with patch.object(self.api, "post", side_effect=lose_before_create) as post:
            with self.assertRaisesRegex(OCE.Blocked, "lost Secret response"):
                self._active()
            with self.assertRaisesRegex(OCE.Blocked, "unknown model Secret create outcome"):
                self._active()
        self.assertEqual(len([call for call in post.call_args_list if
                              call.args[0] == "/namespaces/ns_one/secrets"]), 1)

    def test_lost_binding_patch_and_transport_recover_from_readback(self):
        self.api.lose = "agent-bind"
        with self.assertRaisesRegex(OCE.Blocked, "lost Agent binding response"):
            self._active()
        self.assertEqual(self._journal()["pending"]["operation"], "agent-bind")
        self.api.lose = "runtime-credentials"
        with self.assertRaisesRegex(OCE.Blocked, "lost runtime credential response"):
            self._active()
        self.assertEqual(self._journal()["pending"]["operation"], "runtime-credentials")
        self.assertEqual(self._active()["revisionId"], "rev_one")
        self.assertEqual(len([call for call in self.api.calls if call[0] == "PATCH"]), 1)
        self.assertEqual(len([call for call in self.api.calls if call[0] == "POST-200"]), 1)

    def test_definitive_binding_and_transport_rejections_clear_proven_intents(self):
        with patch.object(self.api, "patch", side_effect=OCE.DefinitiveRejection("HTTP 403")):
            with self.assertRaisesRegex(OCE.DefinitiveRejection, "HTTP 403"):
                self._active()
        self.assertNotIn("pending", self._journal())
        self.assertIsNone(self.api.agents["agt_one"]["harnessAuth"])

        with patch.object(self.api, "post_ok", side_effect=OCE.DefinitiveRejection("HTTP 403")):
            with self.assertRaisesRegex(OCE.DefinitiveRejection, "HTTP 403"):
                self._active()
        self.assertNotIn("pending", self._journal())
        self.assertFalse(self.api.transport_configured)
        self.assertEqual(self._active()["revisionId"], "rev_one")

    def test_partial_runtime_credential_retry_reuses_existing_group(self):
        # Pinned Kubernetes driver reads both groups and only creates absent
        # ones (apps/controller/src/drivers/compute/kubernetes/index.ts).
        groups = {}

        def partial_then_complete(path, body):
            self.assertEqual(body, {})
            self.assertEqual(path, "/namespaces/ns_one/agents/agt_one/runtime-credentials")
            if "transport" not in groups:
                groups["transport"] = "generated-once"
                raise OCE.Blocked("lost runtime credential response")
            self.assertEqual(groups["transport"], "generated-once")
            groups["gateway"] = "generated-once"
            self.api.transport_configured = True
            return {"transportConfigured": True}

        with patch.object(self.api, "post_ok", side_effect=partial_then_complete) as post:
            with self.assertRaisesRegex(OCE.Blocked, "lost runtime credential response"):
                self._active()
            self.assertEqual(self._journal()["pending"]["operation"], "runtime-credentials")
            self.assertEqual(self._active()["revisionId"], "rev_one")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(groups, {"transport": "generated-once",
                                  "gateway": "generated-once"})

    def test_rejected_binding_and_transport_with_changed_readback_stay_pending(self):
        original_patch = self.api.patch

        def changed_binding(path, body):
            original_patch(path, body)
            raise OCE.DefinitiveRejection("HTTP 403")

        with patch.object(self.api, "patch", side_effect=changed_binding):
            with self.assertRaisesRegex(OCE.Blocked, "binding outcome changed"):
                self._active()
        self.assertEqual(self._journal()["pending"]["operation"], "agent-bind")

        original_post = self.api.post_ok

        def changed_transport(path, body):
            original_post(path, body)
            raise OCE.DefinitiveRejection("HTTP 403")

        with patch.object(self.api, "post_ok", side_effect=changed_transport):
            with self.assertRaisesRegex(OCE.Blocked, "credential outcome changed"):
                self._active()
        self.assertEqual(self._journal()["pending"]["operation"], "runtime-credentials")
        self.assertEqual(self._active()["revisionId"], "rev_one")

    def test_lost_deploy_and_stop_recover_without_repost(self):
        self.api.lose = "deploy"
        with self.assertRaisesRegex(OCE.Blocked, "lost deploy response"):
            self._active()
        self.assertEqual(self._journal()["pending"]["operation"], "deploy")
        self.assertEqual(self._active()["revisionId"], "rev_one")
        self.assertEqual(len([call for call in self.api.calls if call[1].endswith("/deploy")]), 1)
        self.api.lose = "stop"
        with self.assertRaisesRegex(OCE.Blocked, "lost stop response"):
            self._stop()
        self.assertEqual(self._journal()["pending"]["operation"], "stop")
        self.assertEqual(self._stop()["desiredRuntimeState"], "stopped")
        self.assertEqual(len([call for call in self.api.calls if call[1].endswith("/stop")]), 1)

    def test_unknown_stop_before_acceptance_never_reposts_or_discards_revision(self):
        self._active()
        revision_id = self._journal()["revisionId"]

        def lose_before_acceptance(path, body=None):
            if path.endswith("/stop"):
                raise OCE.Blocked("stop response unknown before acceptance")
            raise AssertionError("unexpected accepted POST")

        with patch.object(self.api, "post_accepted", side_effect=lose_before_acceptance) as post:
            with self.assertRaisesRegex(OCE.Blocked, "unknown before acceptance"):
                self._stop()
            with self.assertRaisesRegex(OCE.Blocked, "stop outcome is unknown"):
                self._stop()
            self.assertEqual(post.call_count, 1)

        self.assertEqual(self._journal()["pending"], {"operation": "stop"})
        self.assertEqual(self._journal()["revisionId"], revision_id)
        self.assertEqual(self.api.agents["agt_one"]["desiredRuntimeState"], "running")
        with self.assertRaisesRegex(OCE.Blocked, "active journal is incomplete"):
            self._verify()

        # A delayed first request may still complete. Only exact observed
        # termination clears the pending intent; no second stop is sent.
        self.api.agents["agt_one"]["desiredRuntimeState"] = "stopped"
        self.api.agents["agt_one"]["activeRevisionId"] = None
        self.api.runtime_pods = []
        self.assertEqual(self._stop()["revisionId"], revision_id)
        self.assertNotIn("pending", self._journal())
        self.assertFalse(any(call[1].endswith("/stop") for call in self.api.calls))

    def test_admitted_revision_logging_recovers_without_changing_saved_configuration(self):
        installation = (ROOT / "clusters/homelab/apps/openclaw-enterprise/installation.yaml")
        self.assertNotRegex(installation.read_text(), r"(?m)^logging:")
        saved = copy.deepcopy(self.api.configurations["cfg_one"]["values"])
        self.api.lose = "deploy"
        with self.assertRaisesRegex(OCE.Blocked, "lost deploy response"):
            self._active()
        revision = self.api.revisions["rev_one"]
        admitted = copy.deepcopy(saved)
        admitted["logging"] = {"level": "info", "consoleLevel": "info",
                               "consoleStyle": "json"}
        admitted["diagnostics"] = {"otel": {"logs": False}}
        self.assertEqual(revision["configuration"], admitted)
        self.assertEqual(self.api.configurations["cfg_one"]["values"], saved)
        self.assertEqual(self._active()["revisionId"], "rev_one")
        self.assertEqual(self._verify()["desiredRuntimeState"], "running")
        self.assertEqual(len([call for call in self.api.calls if call[1].endswith("/deploy")]), 1)
        revision["configuration"]["diagnostics"]["otel"]["logs"] = True
        with self.assertRaisesRegex(OCE.Blocked, "active revision changed"):
            self._verify()

    def test_unknown_deploy_without_revision_never_reposts(self):
        original_post = self.api.post_accepted

        def lose_before_deploy(path, body=None):
            if path.endswith("/deploy"):
                raise OCE.Blocked("lost deploy response")
            return original_post(path, body)

        with patch.object(self.api, "post_accepted", side_effect=lose_before_deploy) as post:
            with self.assertRaisesRegex(OCE.Blocked, "lost deploy response"):
                self._active()
            with self.assertRaisesRegex(OCE.Blocked, "deploy outcome remains unknown"):
                self._active()
        self.assertEqual(len([call for call in post.call_args_list if
                              call.args[0].endswith("/deploy")]), 1)

    def test_foreign_grant_and_key_version_block(self):
        self.api.roles["role_foreign"] = {
            "id": "role_foreign", "namespaceId": "ns_one", "name": "foreign",
            "permissions": [{"action": "operate", "resourceKind": "secret"}]}
        with self.assertRaisesRegex(OCE.Blocked, "unjournaled exact model Role"):
            self._active()
        self.api.roles.clear()
        self._active()
        self.credential["version"] = 2
        with self.assertRaisesRegex(OCE.Blocked, "model key version changed"):
            self._active()

    def test_foreign_agent_integrations_block_before_active_mutation(self):
        foreign = {
            "plugins": {"example": {"enabled": True}},
            "pluginApprovers": [{"channel": "slack", "id": "owner"}],
            "repositoryBindings": [{"repositoryRef": "private-repo"}],
            "repositoryAccess": {"defaultProfile": "write", "repositories": []},
            "credentialSources": [{"sourceId": "cs_foreign"}],
        }
        writes = len([call for call in self.api.calls if call[0].startswith("POST") or
                      call[0] == "PATCH"])
        agent = self.api.agents["agt_one"]
        for field, value in foreign.items():
            with self.subTest(field=field):
                agent[field] = value
                with self.assertRaisesRegex(OCE.Blocked, "foreign integrations"):
                    self._active()
                agent.pop(field)
                self.assertEqual(self.api.secrets, {})
                self.assertEqual(len([call for call in self.api.calls if
                                      call[0].startswith("POST") or call[0] == "PATCH"]), writes)
        agent.pop("harnessAuth")
        agent["configurationReadError"] = {
            "code": "SAVED_CONFIGURATION_UNREADABLE", "field": "plugins"}
        with self.assertRaisesRegex(OCE.Blocked, "unreadable settings"):
            self._active()

    def test_foreign_revision_integrations_block_repeat_and_verify(self):
        self._active()
        writes = len([call for call in self.api.calls if call[0].startswith("POST") or
                      call[0] == "PATCH"])
        revision = self.api.revisions["rev_one"]
        foreign = {
            "plugins": {"driver": {"id": "foreign", "implementation": "foreign"},
                        "plugins": {"example": {"enabled": True}}},
            "pluginApprovers": [{"channel": "slack", "id": "owner"}],
            "repositoryCredentials": {"bindings": [{"repositoryRef": "private-repo"}]},
            "credentialSources": [{"sourceId": "cs_foreign"}],
            "secretBindings": {"TOKEN": {"source": {"id": "sec_foreign"}}},
        }
        for field, value in foreign.items():
            with self.subTest(field=field):
                revision[field] = value
                with self.assertRaisesRegex(OCE.Blocked, "active revision changed"):
                    self._verify()
                with self.assertRaisesRegex(OCE.Blocked, "active revision changed"):
                    self._active()
                revision.pop(field)
        self.assertEqual(len([call for call in self.api.calls if
                              call[0].startswith("POST") or call[0] == "PATCH"]), writes)

    def test_plugin_added_during_bind_blocks_before_transport_or_deploy(self):
        original_patch = self.api.patch

        def bind_then_add_plugin(path, body):
            response = original_patch(path, body)
            self.api.agents["agt_one"]["plugins"] = {"foreign": {"enabled": True}}
            return response

        with patch.object(self.api, "patch", side_effect=bind_then_add_plugin):
            with self.assertRaisesRegex(OCE.Blocked, "foreign integrations"):
                self._active()
        self.assertEqual(self._journal()["pending"]["operation"], "agent-bind")
        self.assertFalse(any(call[1].endswith(("/runtime-credentials", "/deploy")) and
                             call[0].startswith("POST") for call in self.api.calls))

    def test_repository_access_added_after_bind_blocks_deploy(self):
        original_post = self.api.post_ok

        def transport_then_add_repository(path, body):
            response = original_post(path, body)
            self.api.agents["agt_one"]["repositoryAccess"] = {
                "defaultProfile": "write", "repositories": []}
            return response

        with patch.object(self.api, "post_ok", side_effect=transport_then_add_repository):
            with self.assertRaisesRegex(OCE.Blocked, "foreign integrations"):
                self._active()
        self.assertNotIn("pending", self._journal())
        self.assertEqual(self.api.revisions, {})
        self.assertFalse(any(call[1].endswith("/deploy") for call in self.api.calls))

    def test_partial_grant_and_revoked_read_permission_block_without_writes(self):
        self._active()
        self.api.bindings["binding_one"]["resourceId"] = "sec_other"
        writes = len([call for call in self.api.calls if call[0].startswith("POST") or
                      call[0] == "PATCH"])
        with self.assertRaisesRegex(OCE.Blocked, "AccessBinding changed"):
            self._verify()
        with self.assertRaisesRegex(OCE.Blocked, "AccessBinding changed"):
            self._active()
        self.api.bindings["binding_one"]["resourceId"] = "sec_one"
        original_get = self.api.get

        def deny_role(path):
            if path.endswith("/iam/roles"):
                raise OCE.DefinitiveRejection("HTTP 403")
            return original_get(path)

        with patch.object(self.api, "get", side_effect=deny_role):
            with self.assertRaisesRegex(OCE.DefinitiveRejection, "HTTP 403"):
                self._active()
        self.assertEqual(len([call for call in self.api.calls if
                              call[0].startswith("POST") or call[0] == "PATCH"]), writes)

    def test_revision_pagination_and_generation_drift_block(self):
        self._active()
        with patch.object(self.api, "revisions_page", return_value={
                "data": [], "meta": {"nextCursor": "v1.1"}}):
            with self.assertRaisesRegex(OCE.Blocked, "revision pagination"):
                self._active()
        self.api.configurations["cfg_one"]["generation"] = 2
        with self.assertRaisesRegex(OCE.Blocked, "Configuration readback changed"):
            self._active()

    def test_stop_waits_for_pointer_and_pods(self):
        self._active()
        original_post = self.api.post_accepted

        def queued_stop(path, body=None):
            response = original_post(path, body)
            self.api.agents["agt_one"]["activeRevisionId"] = "rev_one"
            self.api.runtime_pods = [{"name": "agent-one"}]
            return response

        with patch.object(self.api, "post_accepted", side_effect=queued_stop):
            with self.assertRaisesRegex(OCE.Blocked, "still in progress"):
                self._stop()
        self.assertEqual(self._journal()["pending"]["operation"], "stop")
        self.api.agents["agt_one"]["activeRevisionId"] = None
        with self.assertRaisesRegex(OCE.Blocked, "still has Pods"):
            self._stop()
        self.api.runtime_pods = []
        self.assertEqual(self._stop()["desiredRuntimeState"], "stopped")

    def test_stop_without_journaled_revision_fails_closed(self):
        with self.assertRaisesRegex(OCE.Blocked, "requires a journaled revision"):
            self._stop()
        self.assertFalse(any(call[1].endswith("/stop") for call in self.api.calls))


if __name__ == "__main__":
    unittest.main()
