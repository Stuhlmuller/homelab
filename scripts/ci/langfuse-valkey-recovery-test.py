"""Exercise backup integrity and candidate-only repair without production data."""

import importlib.util
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import tarfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "recovery", Path(__file__).resolve().parents[1] / "langfuse-valkey-recovery.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CHECKER = None


class ManifestTests(unittest.TestCase):
    def test_inspector_retirement_keeps_writers_offline(self):
        app = MODULE.ROOT / "clusters/homelab/apps/langfuse"
        values = json.loads(subprocess.check_output(
            ["yq", "-o=json", ".langfuse", str(app / "values.yaml")], text=True))
        self.assertEqual([values["replicas"], values["web"]["replicas"], values["worker"]["replicas"]], [0, 0, 0])
        valkey = json.loads(subprocess.check_output(
            ["yq", "-o=json", 'select(.metadata.name == "langfuse-valkey" and .kind == "Deployment")',
             str(app / "datastores.yaml")], text=True))
        self.assertEqual(valkey["spec"]["replicas"], 0)
        self.assertNotIn("valkey-inspection.yaml", (app / "kustomization.yaml").read_text())


class OfflineGuardTests(unittest.TestCase):
    def setUp(self):
        self.deployments = [{"metadata": {"name": name, "generation": 2},
                             "spec": {"replicas": 0}, "status": {"observedGeneration": 2}}
                            for name in MODULE.WRITERS]
        self.pod = {
            "metadata": {"name": "langfuse-valkey-inspection-test", "uid": "test",
                         "labels": {"app.kubernetes.io/name": "langfuse-valkey-inspection"}},
            "status": {"phase": "Running", "containerStatuses": [{"ready": True}]},
            "spec": {"automountServiceAccountToken": False,
                     "volumes": [{"name": "source", "persistentVolumeClaim": {
                         "claimName": "langfuse-valkey-data", "readOnly": True}}],
                     "containers": [{"image": MODULE.IMAGE,
                                     "command": ["/bin/sh", "-ec", "exec sleep infinity"],
                                     "volumeMounts": [{"name": "source", "mountPath": "/source", "readOnly": True}]}]}}

    def test_offline_reader_allowed(self):
        self.assertEqual(MODULE.offline_pod(self.deployments, [self.pod]),
                         ("langfuse-valkey-inspection-test", "test"))

    def test_running_or_terminating_writer_rejected(self):
        writer = copy.deepcopy(self.pod)
        writer["metadata"] = {"name": "langfuse-worker-old", "deletionTimestamp": "now"}
        with self.assertRaises(AssertionError):
            MODULE.offline_pod(self.deployments, [self.pod, writer])
        self.deployments[0]["spec"]["replicas"] = 1
        with self.assertRaises(AssertionError):
            MODULE.offline_pod(self.deployments, [self.pod])

    def test_writable_source_rejected(self):
        self.pod["spec"]["volumes"][0]["persistentVolumeClaim"]["readOnly"] = False
        with self.assertRaises(AssertionError):
            MODULE.offline_pod(self.deployments, [self.pod])

    def test_promotion_requires_both_writable_mount_flags(self):
        with self.assertRaises(AssertionError):
            MODULE.offline_pod(self.deployments, [self.pod], writable=True)
        self.pod['spec']['volumes'][0]['persistentVolumeClaim']['readOnly'] = False
        self.pod['spec']['containers'][0]['volumeMounts'][0]['readOnly'] = False
        self.assertEqual(MODULE.offline_pod(self.deployments, [self.pod], writable=True)[1], 'test')

    def test_api_omits_default_false_flags(self):
        del self.pod['spec']['volumes'][0]['persistentVolumeClaim']['readOnly']
        del self.pod['spec']['containers'][0]['volumeMounts'][0]['readOnly']
        self.assertEqual(MODULE.offline_pod(self.deployments, [self.pod], writable=True)[1], 'test')
        with self.assertRaises(AssertionError):
            MODULE.offline_pod(self.deployments, [self.pod])
        self.pod['spec']['containers'][0]['volumeMounts'][0]['readOnly'] = True
        with self.assertRaises(AssertionError):
            MODULE.offline_pod(self.deployments, [self.pod], writable=True)


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.name = 'appendonlydir/appendonly.aof.4.incr.aof'
        for part, data in (('source', b'valid-corrupt'), ('inspection/original', b'valid-corrupt'),
                           ('inspection/candidate', b'valid')):
            path = self.root / part / self.name
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
        before = MODULE.fingerprint(self.root / 'source')
        after = MODULE.fingerprint(self.root / 'inspection/candidate')
        self.report = dict(source_unchanged=True, backup_verified=True, candidate_valid=True,
                           before=before, candidate=after, discarded_bytes=8)
        (self.root / 'inspection/report.json').write_text(json.dumps(self.report))
        with tarfile.open(self.root / 'original.tar', 'w') as bundle:
            bundle.add(self.root / 'source', arcname='.')
        with (self.root / 'original.tar').open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        (self.root / 'original.tar.sha256').write_text(digest + '  original.tar\n')
        self.before = {name: entry['sha256'] for name, entry in before.items()}
        self.after = {name: entry['sha256'] for name, entry in after.items()}
        self.stage = 'appendonlydir/.homelab-repaired-' + self.after[self.name]

    def test_source_requires_exact_loss_backup_and_prefix(self):
        self.assertEqual(MODULE.promotion_source(self.root, 8)[0], self.name)
        with self.assertRaises(AssertionError):
            MODULE.promotion_source(self.root, 9)
        (self.root / 'inspection/candidate' / self.name).write_bytes(b'other')
        self.report['candidate'] = MODULE.fingerprint(self.root / 'inspection/candidate')
        (self.root / 'inspection/report.json').write_text(json.dumps(self.report))
        with self.assertRaises(AssertionError):
            MODULE.promotion_source(self.root, 8)

    def test_changed_backup_rejected(self):
        (self.root / 'original.tar.sha256').write_text('incorrect')
        with self.assertRaises(AssertionError):
            MODULE.promotion_source(self.root, 8)

    def test_promotion_order_and_idempotency(self):
        staged = {**self.before, self.stage: self.after[self.name]}
        with patch.object(MODULE, 'release_guard') as release, \
                patch.object(MODULE, 'cluster_guard', return_value=('pod', 'uid')), \
                patch.object(MODULE, 'remote_hashes', side_effect=[self.before, staged, staged, self.after]), \
                patch.object(MODULE.subprocess, 'run') as upload, patch.object(MODULE, 'output') as rename:
            MODULE.promote(self.root, 'a' * 40, 8)
            self.assertEqual(release.call_count, 2)
            self.assertEqual(upload.call_count, 1)
            self.assertIn('mv -T', rename.call_args.args[10])
        with patch.object(MODULE, 'release_guard'), \
                patch.object(MODULE, 'cluster_guard', return_value=('pod', 'uid')), \
                patch.object(MODULE, 'remote_hashes', return_value=self.after), \
                patch.object(MODULE.subprocess, 'run') as upload, patch.object(MODULE, 'output') as rename:
            MODULE.promote(self.root, 'a' * 40, 8)
            upload.assert_not_called()
            rename.assert_not_called()

    def test_live_drift_or_bad_upload_never_renames(self):
        for hashes in ([{}], [self.before, self.before, {self.stage: 'wrong'}]):
            with self.subTest(hashes=hashes), patch.object(MODULE, 'release_guard'), \
                    patch.object(MODULE, 'cluster_guard', return_value=('pod', 'uid')), \
                    patch.object(MODULE, 'remote_hashes', side_effect=hashes), \
                    patch.object(MODULE.subprocess, 'run'), patch.object(MODULE, 'output') as rename:
                with self.assertRaises(AssertionError):
                    MODULE.promote(self.root, 'a' * 40, 8)
                rename.assert_not_called()

    def test_writer_change_after_upload_never_renames(self):
        with patch.object(MODULE, 'release_guard'), \
                patch.object(MODULE, 'cluster_guard', side_effect=[('pod', 'uid'), ('pod', 'new-uid')]), \
                patch.object(MODULE, 'remote_hashes', return_value=self.before), \
                patch.object(MODULE.subprocess, 'run'), patch.object(MODULE, 'output') as rename:
            with self.assertRaises(AssertionError):
                MODULE.promote(self.root, 'a' * 40, 8)
            rename.assert_not_called()

    def test_already_promoted_with_leftover_stage_rejected(self):
        with patch.object(MODULE, 'release_guard'), \
                patch.object(MODULE, 'cluster_guard', return_value=('pod', 'uid')), \
                patch.object(MODULE, 'remote_hashes', return_value={**self.after, self.stage: 'partial'}), \
                patch.object(MODULE.subprocess, 'run') as upload:
            with self.assertRaises(AssertionError):
                MODULE.promote(self.root, 'a' * 40, 8)
            upload.assert_not_called()


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source"
        aof = self.source / "appendonlydir"
        aof.mkdir(parents=True)
        (aof / "appendonly.aof.manifest").write_text("file tail.aof seq 1 type i\n")
        (aof / "tail.aof").write_bytes(b"valid-corrupt")
        self.destination = self.root / "inspection"

    def checker(self, command, **kwargs):
        manifest = Path(command[-1])
        self.assertTrue(manifest.is_relative_to(self.destination / "candidate"))
        self.assertEqual(kwargs["timeout"], 300)
        tail = manifest.parent / "tail.aof"
        if "--fix" in command:
            tail.write_bytes(b"valid")
        return subprocess.CompletedProcess(command, int(tail.read_bytes() != b"valid"))

    def test_repair_only_changes_candidate_and_reports_loss(self):
        before = MODULE.fingerprint(self.source)
        with patch.object(MODULE.subprocess, "run", side_effect=self.checker):
            report = MODULE.prepare(self.source, self.destination, "checker")
        self.assertEqual(MODULE.fingerprint(self.source), before)
        self.assertEqual(MODULE.fingerprint(self.destination / "original"), before)
        self.assertEqual(report["discarded_bytes"], 8)
        self.assertFalse(report["live_replacement_authorized"])
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o700)

    def test_native_checker_repairs_only_corrupt_tail(self):
        if CHECKER is None:
            self.skipTest("Pass --checker for the pinned native checker integration test")
        valid = b"*3\r\n$3\r\nSET\r\n$3\r\nkey\r\n$5\r\nvalue\r\n"
        tail = self.source / "appendonlydir/tail.aof"
        tail.write_bytes(valid + b"CORRUPT\r\n")
        report = MODULE.prepare(self.source, self.destination, CHECKER)
        self.assertEqual(tail.read_bytes(), valid + b"CORRUPT\r\n")
        self.assertEqual((self.destination / "candidate/appendonlydir/tail.aof").read_bytes(), valid)
        self.assertEqual(report["discarded_bytes"], 9)

    def test_source_change_refuses_acceptance(self):
        def changing_checker(command, **kwargs):
            result = self.checker(command, **kwargs)
            (self.source / "appendonlydir/tail.aof").write_bytes(b"changed")
            return result
        with patch.object(MODULE.subprocess, "run", side_effect=changing_checker):
            with self.assertRaisesRegex(ValueError, "changed"):
                MODULE.prepare(self.source, self.destination, "checker")
        self.assertFalse((self.destination / "report.json").exists())

    def test_healthy_copy_is_not_repaired(self):
        (self.source / "appendonlydir/tail.aof").write_bytes(b"valid")
        with patch.object(MODULE.subprocess, "run", side_effect=self.checker) as run:
            report = MODULE.prepare(self.source, self.destination, "checker")
        self.assertFalse(report["needed_repair"])
        self.assertEqual(report["discarded_bytes"], 0)
        self.assertEqual(run.call_count, 2)

    def test_manifest_cannot_escape_candidate(self):
        (self.source / "appendonlydir/appendonly.aof.manifest").write_text(
            "file ../../outside.aof seq 1 type i\n")
        with patch.object(MODULE.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "unsupported member"):
                MODULE.prepare(self.source, self.destination, "checker")
            run.assert_not_called()

    def test_failed_checker_preserves_backup(self):
        with patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(ValueError, "repair failed"):
                MODULE.prepare(self.source, self.destination, "checker")
        self.assertEqual(MODULE.fingerprint(self.source), MODULE.fingerprint(self.destination / "original"))

    def test_rejects_nested_destination_symlinks_and_reuse(self):
        with self.assertRaises(ValueError):
            MODULE.prepare(self.source, self.source / "backup", "checker")
        (self.source / "linked").symlink_to(self.source / "appendonlydir/tail.aof")
        with self.assertRaises(ValueError):
            MODULE.prepare(self.source, self.destination, "checker")
        (self.source / "linked").unlink()
        self.destination.mkdir()
        with self.assertRaises(FileExistsError):
            MODULE.prepare(self.source, self.destination, "checker")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checker")
    args, remaining = parser.parse_known_args()
    CHECKER = args.checker
    unittest.main(argv=[__file__, *remaining])
