#!/usr/bin/env python3
"""Offline failure fixtures for Enterprise-to-legacy recovery boundaries."""

import copy
import importlib.util
import json
import os
import re
import runpy
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load("oce_recovery_base", ROOT / "scripts/ci/openclaw-enterprise-test.py")
LEGACY = load("oce_recovery_legacy", ROOT / "scripts/ci/openclaw-retirement-test.py")
OCE = BASE.OCE
CLEANUP = runpy.run_path(str(ROOT / "scripts/network-policy-cleanup.py"))


def backup_tools_path(cache):
    """Run the Linux backup fixture with real GNU tools on macOS too."""
    path = os.environ["PATH"]
    if sys.platform != "darwin":
        return path

    def has_gnu_tools(candidate):
        for name in ("find", "sort", "cp", "mv", "sha256sum"):
            executable = shutil.which(name, path=candidate)
            if executable is None:
                return False
            try:
                result = subprocess.run([executable, "--version"], text=True,
                                        capture_output=True, timeout=5, check=False)
            except (OSError, subprocess.TimeoutExpired):
                return False
            if result.returncode != 0 or "GNU" not in result.stdout:
                return False
        return True

    if has_gnu_tools(path):
        return path
    cache.mkdir(mode=0o700)
    environment = {**os.environ, "XDG_CACHE_HOME": str(cache)}
    try:
        result = subprocess.run(
            ["nix", "develop", "--command", "sh", "-c", 'printf %s "$PATH"'],
            cwd=ROOT, env=environment, text=True, capture_output=True,
            timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise AssertionError("GNU backup tools are unavailable from the Nix development shell") from None
    if result.returncode != 0 or not has_gnu_tools(result.stdout):
        raise AssertionError("GNU backup tools are unavailable from the Nix development shell")
    return result.stdout


class RecoveryBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oce-recovery-")
        self.addCleanup(self.temp.cleanup)
        private = Path(self.temp.name).resolve() / "private"
        private.mkdir(mode=0o700)
        self.config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        self.config["privateJournal"]["mountPath"] = str(private / "journal.json")
        self.api = BASE.ActiveTenantAPI()
        self.kube = BASE.TenantKubernetes(self.api)
        with OCE.ProtectedJournal(private / "journal.json", self.config["source"]["revision"],
                                  OCE._identity_hash(self.config)) as journal:
            journal.save({"installationId": "ins_one", "namespaceId": "ns_one"})
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}):
            OCE.reconcile(self.config, self.api, self.kube, "a" * 40)
        self.config["activationEnabled"] = True

    def active(self):
        # Stage the first revision directly: public reconcile remains blocked
        # until an owner reviews the returned native origin.
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}):
            OCE.reconcile_active(self.config, self.api, self.kube,
                                 {"version": 1, "key": "fixture-openrouter-key"})

    def stop(self):
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}):
            return OCE.stop_agent(self.config, self.api, self.kube, "a" * 40)

    def journal(self):
        return OCE.read_journal(self.config["privateJournal"]["mountPath"],
                                self.config["source"]["revision"],
                                OCE._identity_hash(self.config))[0]

    def test_unknown_stop_keeps_new_state_and_cannot_prove_termination(self):
        self.active()
        before = {key: copy.deepcopy(getattr(self.api, key)) for key in
                  ("secrets", "roles", "bindings", "configurations", "revisions", "deployments")}
        revision = self.journal()["revisionId"]
        with patch.object(self.api, "post_accepted", side_effect=OCE.Blocked("stop response lost")) as post:
            with self.assertRaisesRegex(OCE.Blocked, "stop response lost"):
                self.stop()
            with self.assertRaisesRegex(OCE.Blocked, "stop outcome is unknown"):
                self.stop()
        post.assert_called_once()
        self.assertEqual(self.journal()["pending"], {"operation": "stop"})
        self.assertEqual(self.journal()["revisionId"], revision)
        self.assertEqual(self.api.agents["agt_one"]["desiredRuntimeState"], "running")
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}):
            with self.assertRaises(OCE.Blocked):
                OCE.reconcile(self.config, self.api, self.kube, "a" * 40,
                              {"version": 1, "key": "fixture-openrouter-key"})
        for key, value in before.items():
            self.assertEqual(getattr(self.api, key), value, key)
        self.assertFalse(any(call[0] == "DELETE" for call in self.api.calls))

    def test_unavailable_control_plane_blocks_native_stop_without_new_write(self):
        self.active()
        before = self.journal()
        with patch.object(self.api, "get", side_effect=OCE.Blocked("control plane unavailable")):
            with self.assertRaisesRegex(OCE.Blocked, "control plane unavailable"):
                self.stop()
        self.assertEqual(self.journal(), before)
        self.assertFalse(any(call[1].endswith("/stop") for call in self.api.calls))

    def test_interrupted_runtime_read_cannot_clear_stop_intent(self):
        self.active()
        self.api.lose = "stop"
        with self.assertRaisesRegex(OCE.Blocked, "lost stop response"):
            self.stop()
        revision = self.journal()["revisionId"]
        runtime_path = "/namespaces/ns_one/agents/agt_one/deployments/rev_one/runtime"
        original_get = self.api.get
        for response in ({"revisionId": revision, "observedAt": "now",
                          "pods": [{"name": "agent-one", "phase": "Unknown"}]},
                         {"revisionId": "rev_other", "observedAt": "now", "pods": []},
                         {"revisionId": revision, "pods": []},
                         OCE.Blocked("runtime read unavailable")):
            with self.subTest(response=response):
                def read(path):
                    if path == runtime_path:
                        if isinstance(response, Exception):
                            raise response
                        return response
                    return original_get(path)

                with patch.object(self.api, "get", side_effect=read):
                    with self.assertRaises(OCE.Blocked):
                        self.stop()
                self.assertEqual(self.journal()["pending"], {"operation": "stop"})
                self.assertEqual(self.journal()["revisionId"], revision)
        self.assertEqual(len([call for call in self.api.calls if call[1].endswith("/stop")]), 1)
        writes = [call for call in self.api.calls if call[0] in
                  {"POST", "POST-200", "POST-202", "PATCH", "DELETE"}]
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}):
            with self.assertRaises(OCE.Blocked):
                OCE.reconcile(self.config, self.api, self.kube, "a" * 40,
                              {"version": 1, "key": "fixture-openrouter-key"})
        self.assertEqual([call for call in self.api.calls if call[0] in
                          {"POST", "POST-200", "POST-202", "PATCH", "DELETE"}], writes)
        self.assertEqual(self.journal()["pending"], {"operation": "stop"})
        self.api.runtime_pods = []
        self.assertEqual(self.stop()["revisionId"], revision)
        self.assertNotIn("pending", self.journal())

    def test_native_stop_precedes_both_runtime_termination_proofs(self):
        self.active()
        events = []
        original_post = self.api.post_accepted
        original_get = self.api.get
        original_absent = self.kube.tenant_pods_absent

        def post(path, body=None):
            if path.endswith("/stop"):
                events.append("native-stop")
            return original_post(path, body)

        def get(path):
            if path.endswith("/runtime"):
                events.append("runtime-empty")
            return original_get(path)

        def tenant_pods_absent():
            events.append("tenant-pods-empty")
            return original_absent()

        with patch.object(self.api, "post_accepted", side_effect=post), \
             patch.object(self.api, "get", side_effect=get), \
             patch.object(self.kube, "tenant_pods_absent", side_effect=tenant_pods_absent):
            self.assertEqual(self.stop()["desiredRuntimeState"], "stopped")
        self.assertEqual(events, ["native-stop", "runtime-empty", "tenant-pods-empty"])
        self.assertNotIn("pending", self.journal())

    def test_orphan_tenant_pod_keeps_stop_pending_without_reposting(self):
        self.active()
        self.kube.tenant_pods = [{"name": "orphan-agent", "phase": "Unknown"}]
        before = copy.deepcopy(self.api.revisions)
        with self.assertRaisesRegex(OCE.Blocked, "tenant still has Pods"):
            self.stop()
        self.assertEqual(self.journal()["pending"], {"operation": "stop"})
        self.assertEqual(self.api.revisions, before)
        self.assertEqual(self.api.agents["agt_one"]["desiredRuntimeState"], "stopped")
        self.assertEqual(len([call for call in self.api.calls if call[1].endswith("/stop")]), 1)
        with self.assertRaisesRegex(OCE.Blocked, "tenant still has Pods"):
            self.stop()
        self.assertEqual(len([call for call in self.api.calls if call[1].endswith("/stop")]), 1)
        self.kube.tenant_pods = []
        self.assertEqual(self.stop()["desiredRuntimeState"], "stopped")
        self.assertNotIn("pending", self.journal())

    def test_incomplete_or_nonempty_tenant_pod_list_cannot_prove_stop(self):
        kube = OCE.Kubernetes.__new__(OCE.Kubernetes)
        empty = {"kind": "PodList", "metadata": {"resourceVersion": "42"},
                 "items": []}
        with patch.object(kube, "_json", return_value=empty) as read:
            kube.tenant_pods_absent()
        read.assert_called_once_with("get", "--raw", "/api/v1/namespaces/openclaw-agents/pods")
        for listing in (
            {**empty, "metadata": {}},
            {**empty, "metadata": {"resourceVersion": "42", "continue": "next"}},
            {**empty, "items": [{"status": {"phase": "Unknown"}}]},
        ):
            with self.subTest(listing=listing), patch.object(kube, "_json", return_value=listing):
                with self.assertRaisesRegex(OCE.Blocked, "Pod list is uncertain"):
                    kube.tenant_pods_absent()

    def test_restore_stage_remains_blocked_before_recovery_orchestration(self):
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                       text=True).strip()
        fake_gh = Path(self.temp.name) / "gh"
        fake_gh.write_text('#!/bin/sh\nprintf "%s\\n" "$FAKE_MAIN_SHA"\n')
        fake_gh.chmod(0o755)
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/ci/openclaw-enterprise-stage.sh"), "restore"],
            cwd=ROOT, env={**os.environ, "GITHUB_ACTIONS": "true",
                           "GITHUB_SHA": head, "EXPECTED_SHA": head,
                           "GITHUB_REF": "refs/heads/main",
                           "GITHUB_REPOSITORY": "Stuhlmuller/homelab",
                           "GH_REPO": "Stuhlmuller/homelab", "GH_TOKEN": "test",
                           "FAKE_MAIN_SHA": head,
                           "PATH": f'{self.temp.name}:{os.environ["PATH"]}'},
            capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("restore blocked: durable private journal runner is not declared",
                      result.stderr)

    def test_legacy_archive_remains_recoverable_after_new_stop_failure(self):
        fixture = LEGACY.Retirement(
            "test_full_local_and_nas_archive_restores_checkpoint_and_databases")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            receipt = LEGACY.retirement.archive(
                fixture.config, fixture.status_path, fixture.baseline_path,
                fixture.observed_path, fixture.archive_root)
        expected = LEGACY.retirement.verify_archive(fixture.config, receipt)
        self.assertEqual(set(expected["restoredDatabases"]), set(fixture.config["requiredLocal"]))
        bundle = receipt.parent / "legacy.tar.gz"
        archive_sha = LEGACY.retirement.digest(bundle)
        self.active()
        new_state = self.journal()
        with patch.object(self.api, "post_accepted", side_effect=OCE.Blocked("stop unavailable")):
            with self.assertRaisesRegex(OCE.Blocked, "stop unavailable"):
                self.stop()
        incompatible = dict(fixture.config, localClaim="unrelated-claim")
        with self.assertRaisesRegex(ValueError, "committed recovery contract"):
            LEGACY.retirement.verify_archive(incompatible, receipt)
        self.assertEqual(LEGACY.retirement.verify_archive(fixture.config, receipt), expected)
        self.assertEqual(LEGACY.retirement.digest(bundle), archive_sha)
        self.assertEqual(self.api.agents["agt_one"]["desiredRuntimeState"], "running")
        self.assertEqual(self.journal()["pending"], {"operation": "stop"})
        self.api.agents["agt_one"].update(desiredRuntimeState="stopped", activeRevisionId=None)
        self.api.runtime_pods = []
        self.assertEqual(self.stop()["desiredRuntimeState"], "stopped")
        recovery = fixture.archive_root / "recovery-copy"
        self.assertEqual(LEGACY.retirement.verify_archive(fixture.config, receipt, recovery),
                         expected)
        self.assertTrue((recovery / "completed.json").is_file())
        self.assertTrue((recovery / "tree/local/state/openclaw.sqlite").is_file())
        self.assertEqual(LEGACY.retirement.digest(bundle), archive_sha)
        self.assertEqual(self.journal(), new_state)

    def test_owned_claims_and_database_survive_declarative_retirement(self):
        for path, names, kind in (
            (ROOT / "clusters/homelab/apps/openclaw/runtime-storage.yaml",
             {"openclaw-runtime-local", "openclaw-runtime-state-local",
              "openclaw-runtime-agent-local"}, "PersistentVolumeClaim"),
            (ROOT / "clusters/homelab/platform/storage/openclaw-runtime.yaml",
             {"openclaw-runtime-local", "openclaw-runtime-state-local",
              "openclaw-runtime-agent-local"}, "PersistentVolume"),
            (ROOT / "clusters/homelab/apps/openclaw/retirement-storage.yaml",
             {"openclaw-retirement-archive"}, "PersistentVolumeClaim"),
        ):
            documents = [item for item in path.read_text().split("\n---\n")
                         if re.search(r"(?m)^kind: " + kind + r"$", item)]
            self.assertEqual({re.search(r"(?m)^  name: ([a-z0-9-]+)$", item).group(1)
                              for item in documents}, names)
            for item in documents:
                self.assertIn("argocd.argoproj.io/sync-options: Prune=false", item)
                if kind == "PersistentVolume":
                    self.assertIn("persistentVolumeReclaimPolicy: Retain", item)
        postgres = (ROOT / "clusters/homelab/apps/openclaw-enterprise-foundation/postgres.yaml").read_text()
        self.assertIn("persistentVolumeClaimRetentionPolicy:\n    whenDeleted: Retain\n    whenScaled: Retain", postgres)
        self.assertIn("name: occ-postgres\n        annotations:\n          argocd.argoproj.io/sync-options: Prune=false", postgres)
        journal = (ROOT / "clusters/homelab/apps/openclaw-enterprise-operator/journal.yaml").read_text()
        self.assertIn("reclaimPolicy: Retain", journal)
        self.assertIn("name: occ-operator-journal", journal)
        self.assertIn("argocd.argoproj.io/sync-options: Prune=false", journal)
        self.assertIn("argocd.argoproj.io/sync-options: Prune=false,Delete=false",
                      (ROOT / "clusters/homelab/apps/openclaw/values.yaml").read_text())

    def test_enforcement_removal_blocks_running_or_unknown_agent_pod(self):
        tenant = {"kind": "Pod", "metadata": {"namespace": "openclaw-agents",
                                              "name": "agent-one"},
                  "status": {"phase": "Running"}}
        canary = CLEANUP["CANARY"]
        node = {"metadata": {"uid": "node-uid", "labels": {canary: "true"}},
                "spec": {"taints": [{"key": canary, "value": "true",
                                      "effect": "NoSchedule"}]},
                "status": {"nodeInfo": {"bootID": "node-boot"},
                           "conditions": [{"type": "Ready", "status": "True"}]}}
        placement = {"nodeUid": "node-uid", "bootID": "node-boot"}
        for phase in ("Running", "Unknown"):
            with self.subTest(phase=phase):
                tenant["status"]["phase"] = phase
                reads = []
                commands = []

                def kubernetes_json(*args):
                    reads.append(args)
                    if args == ("get", "node", "zimaboard-1"):
                        return node
                    if args == ("get", "pods,deployments,statefulsets,replicasets,"
                                "daemonsets,jobs,cronjobs", "-A", "--chunk-size=0"):
                        return {"metadata": {}, "items": [tenant]}
                    raise AssertionError(f"unexpected Kubernetes read: {args}")

                def command(*args):
                    commands.append(args)
                    raise AssertionError(f"cleanup command ran before quiescence: {args}")

                with patch.dict(CLEANUP["inspect_cluster"].__globals__,
                                {"kubernetes_json": kubernetes_json,
                                 "command": command}):
                    with self.assertRaisesRegex(ValueError, "not quiesced"):
                        CLEANUP["inspect_cluster"](
                            {"canary": {"node": "zimaboard-1"}}, placement)
                self.assertEqual(len(reads), 2)
                self.assertEqual(commands, [])
        tenant["status"]["phase"] = "Succeeded"
        CLEANUP["ensure_quiesced"]([tenant])

    def test_backup_refuses_unstopped_or_unidentified_recovery_material(self):
        material = Path(self.temp.name) / "material"
        material.mkdir()
        source = (ROOT / "clusters/homelab/apps/openclaw-enterprise-foundation/backup.sh").read_text()
        marker_check = (source.split('stopped_marker() {', 1)[1]
                        .split('material_manifest() (', 1)[0])
        preflight = 'stopped_marker() {' + marker_check + '\nstopped_marker "$1"\n'
        marker = material / "recovery.json"
        for payload in ('{"claimUid":"fixture","writerStopped":false}',
                        '{"claimUid":"","writerStopped":true}',
                        '{"claimUid":"fixture","writerStopped":true,'
                        '"continuousFenceVerified":false}',
                        '{"claimUid":"fixture"}', '{',
                        '{"claimUid":"fixture","writerStopped":false}'
                        '{"claimUid":"fixture","writerStopped":true}'):
            with self.subTest(payload=payload):
                marker.write_text(payload)
                result = subprocess.run(["bash", "-c", preflight, "--", str(marker)], text=True,
                                        capture_output=True, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "")
        marker.write_text('{"claimUid":"fixture","writerStopped":true,'
                          '"continuousFenceVerified":true}')
        result = subprocess.run(["bash", "-c", preflight, "--", str(marker)], text=True,
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_backup_rejects_material_changed_during_copy(self):
        root = Path(self.temp.name)
        material = root / "material"
        for name in ("postgres-root/tls.crt", "postgres-root/tls.key",
                     "postgres-admin/password", "postgres-migrator/password",
                     "postgres-app/password", "postgres-backup/password",
                     "auth/secret", "gateway/occ", "gateway-ca/tls.crt",
                     "gateway-ca/tls.key", "bootstrap/output.json",
                     "bootstrap/initial-admin-password",
                     "bootstrap/initial-admin-service-key.json",
                     "journal/journal.json", "tenant/metadata.json",
                     "agent/identity.json", "tenant/secrets/key", "agent/state/state.db"):
            target = material / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixture-secret")
        (material / "recovery.json").write_text(
            '{"claimUid":"fixture","writerStopped":true,'
            '"continuousFenceVerified":true}')
        backup = root / "backup"
        backup.mkdir()
        scratch = root / "scratch"
        scratch.mkdir()
        fake_bin = root / "bin"
        fake_bin.mkdir()
        (fake_bin / "pg_dump").write_text(
            '#!/bin/sh\nfor arg do case "$arg" in --file=*) '
            'printf fixture-dump > "${arg#--file=}";; esac; done\n')
        (fake_bin / "pg_restore").write_text("#!/bin/sh\nexit 0\n")
        for name in ("pg_dump", "pg_restore"):
            (fake_bin / name).chmod(0o755)
        mountpoint = fake_bin / "mountpoint"
        mountpoint.write_text('#!/bin/sh\n[ "$1" = -q ] && [ "$2" = '
                              + shlex.quote(str(backup.parent)) + ' -o "$2" = '
                              + shlex.quote(str(scratch)) + ' ]\n')
        mountpoint.chmod(0o755)
        (root / "database-bootstrap.sql").write_text("SELECT 1;\n")
        (root / "backup-password").write_text("fixturepassword")
        (root / "postgres-ca.crt").write_text("fixture-ca")
        source = (ROOT / "clusters/homelab/apps/openclaw-enterprise-foundation/backup.sh").read_text()
        for original, replacement in (
            ("/recovery-material", str(material)),
            ("/backup/openclaw-enterprise", str(backup)),
            ("/scratch/openclaw-enterprise", str(scratch / "openclaw-enterprise")),
            ("/run/backup-recipient/age.pub", str(root / "recipient.age")),
            ("/run/secrets/occ-postgres-backup/password", str(root / "backup-password")),
            ("/run/postgres-ca/tls.crt", str(root / "postgres-ca.crt")),
            ("/scripts/database-bootstrap.sql", str(root / "database-bootstrap.sql")),
        ):
            source = source.replace(original, replacement)
        script = root / "backup.sh"
        script.write_text(source)
        tool_path = backup_tools_path(root / "nix-cache")
        identity = root / "age.key"
        keygen = shutil.which("age-keygen", path=tool_path)
        self.assertIsNotNone(keygen)
        self.assertEqual(subprocess.run([keygen, "-o", str(identity)],
                                        capture_output=True, text=True,
                                        check=False).returncode, 0)
        recipient = subprocess.run([keygen, "-y", str(identity)],
                                   capture_output=True, text=True, check=False)
        self.assertEqual(recipient.returncode, 0)
        (root / "recipient.age").write_text(recipient.stdout)
        real_cp = shutil.which("cp", path=tool_path)
        self.assertIsNotNone(real_cp)
        environment = {**os.environ, "PATH": str(fake_bin) + ":" + tool_path}
        mountpoint.write_text('#!/bin/sh\nexit 1\n')
        unmounted = subprocess.run(["bash", str(script)], text=True, capture_output=True,
                                   env=environment, check=False)
        self.assertNotEqual(unmounted.returncode, 0)
        self.assertIn("private backup destination is not mounted", unmounted.stderr)
        self.assertEqual(list(backup.iterdir()), [])
        mountpoint.write_text('#!/bin/sh\n[ "$1" = -q ] && [ "$2" = '
                              + shlex.quote(str(backup.parent)) + ' -o "$2" = '
                              + shlex.quote(str(scratch)) + ' ]\n')
        backup.rmdir()
        container_storage = root / "container-storage"
        container_storage.mkdir()
        backup.symlink_to(container_storage, target_is_directory=True)
        redirected = subprocess.run(["bash", str(script)], text=True, capture_output=True,
                                    env=environment, check=False)
        self.assertNotEqual(redirected.returncode, 0)
        self.assertIn("private backup directory must not be a symlink", redirected.stderr)
        self.assertEqual(list(container_storage.iterdir()), [])
        backup.unlink()
        backup.mkdir()
        baseline = subprocess.run(["bash", str(script)], text=True, capture_output=True,
                                  env=environment, check=False)
        self.assertEqual(baseline.returncode, 0, baseline.stderr)
        self.assertEqual(len(list(backup.iterdir())), 1)
        next(backup.iterdir()).unlink()
        state = material / "agent/state/state.db"
        for mutation in ("content", "symlink"):
            with self.subTest(mutation=mutation):
                state.write_text("fixture-secret")
                if mutation == "content":
                    action = (shlex.quote(real_cp) + ' "$@" || exit\n'
                              + 'printf changed > ' + shlex.quote(str(state)) + '\n')
                else:
                    parked = root / "parked-state.db"
                    action = ('mv ' + shlex.quote(str(state)) + ' '
                              + shlex.quote(str(parked)) + '\n'
                              + 'ln -s ' + shlex.quote(str(root / "postgres-ca.crt"))
                              + ' ' + shlex.quote(str(state)) + '\n'
                              + shlex.quote(real_cp) + ' "$@" || exit\n'
                              + 'rm ' + shlex.quote(str(state)) + '\n'
                              + 'mv ' + shlex.quote(str(parked)) + ' '
                              + shlex.quote(str(state)) + '\n')
                (fake_bin / "cp").write_text(
                    '#!/bin/sh\nif [ "$2" = ' + shlex.quote(str(material)) + ' ]; then\n'
                    + action + 'else\n' + shlex.quote(real_cp) + ' "$@"\nfi\n')
                (fake_bin / "cp").chmod(0o755)
                result = subprocess.run(["bash", str(script)], text=True, capture_output=True,
                                        env=environment, check=False)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("encrypted backup failed at copy", result.stderr)
                self.assertEqual(list(backup.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
