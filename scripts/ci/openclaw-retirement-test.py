#!/usr/bin/env python3
"""Fail-closed legacy retirement and independent restore fixtures."""

import importlib.util
import io
import json
import os
import sqlite3
import stat
import subprocess
import tarfile
import tempfile
import time
import unittest
from contextlib import closing, redirect_stderr
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[2] / 'clusters/homelab/apps/openclaw/retirement/retirement.py'
spec = importlib.util.spec_from_file_location('openclaw_retirement', SOURCE)
retirement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retirement)


class Keepalive(unittest.TestCase):
    def test_long_operation_emits_only_generic_progress(self):
        class Stop:
            calls = 0

            def wait(self, _seconds):
                self.calls += 1
                return self.calls > 1

        output = io.StringIO()
        with redirect_stderr(output):
            retirement.keepalive(Stop())
        self.assertEqual(output.getvalue(), 'Legacy retention operation active\n')


class Retirement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='oce-retirement-')
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.local, self.nas, self.archive_root, self.scratch_root = (
            base / item for item in ('local', 'nas', 'archive', 'scratch'))
        for item in (self.local, self.nas, self.archive_root, self.scratch_root):
            item.mkdir(mode=0o700)
        self.config = {
            'namespace': 'ai', 'node': 'zimaboard-1', 'deployment': 'openclaw',
            'image': 'ghcr.io/openclaw/openclaw:fixture@sha256:abc',
            'assistantSha256': 'fixture-assistant-hash',
            'cronJob': 'openclaw-runtime-backup', 'localClaim': 'openclaw-runtime-local',
            'stateClaim': 'openclaw-runtime-state-local', 'agentClaim': 'openclaw-runtime-agent-local',
            'nasClaim': 'openclaw', 'localRoot': str(self.local), 'nasRoot': str(self.nas),
            'scratchRoot': str(self.scratch_root),
            'localUid': os.getuid(), 'nasUid': os.getuid(),
            'requiredLocal': ['state/openclaw.sqlite', 'agents/main/agent/openclaw-agent.sqlite'],
            'requiredNas': ['openclaw', 'openclaw-backups/pre-2026.9.2-runtime',
                            'openclaw-backups/pre-2026.9.5', 'openclaw-runtime-snapshots'],
            'stateMount': str(self.local / 'state'),
            'agentMount': str(self.local / 'agents/main/agent'),
        }
        for name in self.config['requiredLocal']:
            path = self.local / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(path)) as db:
                with db:
                    db.execute('CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT)')
                    db.execute('INSERT INTO messages (body) VALUES (?)', ('private',))
        for name in self.config['requiredNas']:
            path = self.nas / name
            path.mkdir(parents=True, exist_ok=True)
            (path / 'retained').write_text('private')
        (self.nas / 'unlisted-configuration').write_text('private')
        self.observed = retirement.inventory(self.config)
        self.status = {
            'checkedAt': int(time.time()),
            'namespace': 'ai', 'node': 'zimaboard-1', 'nodeReady': True,
            'deployment': 'openclaw', 'image': self.config['image'],
            'assistantSha256': self.config['assistantSha256'],
            'replicas': 0, 'readyReplicas': 0, 'pods': 0,
            'cronJob': 'openclaw-runtime-backup', 'cronJobSuspended': True,
            'activeJobs': 0, 'claims': self.observed['claims'],
            'volumes': {claim: {'pvcUid': 'pvc-uid-' + claim,
                                'pvName': claim if claim != 'openclaw' else 'pvc-nas-volume',
                                'pvUid': 'pv-uid-' + claim}
                        for claim in self.observed['claims'].values()},
            'roots': {name: {key: item[key] for key in ('device', 'inode', 'uid')}
                      for name, item in self.observed['roots'].items()},
        }
        self.observed = retirement.inventory(self.config, self.status)
        self.baseline = {
            'kubernetes': self.observed['kubernetes'],
            'rootIdentity': self.status['roots'],
        }
        self.status_path = self.archive_root / 'status.json'
        self.baseline_path = self.archive_root / 'baseline.json'
        self.observed_path = self.archive_root / 'observed.json'
        retirement.write_private(self.status_path, self.status)
        retirement.write_private(self.baseline_path, self.baseline)
        retirement.write_private(self.observed_path, dict(self.observed, rootIdentity=self.status['roots']))

    def test_full_local_and_nas_archive_restores_checkpoint_and_databases(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
            receipt = retirement.archive(self.config, self.status_path, self.baseline_path, self.observed_path,
                                         self.archive_root)
        record = retirement.verify_archive(self.config, receipt)
        self.assertEqual(set(record['restoredDatabases']), set(self.config['requiredLocal']))
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
        self.assertEqual(len(list(self.archive_root.glob('legacy-*/receipt.json'))), 1)
        with tarfile.open(receipt.parent / 'legacy.tar.gz', 'r:gz') as bundle:
            names = set(bundle.getnames())
        self.assertIn('nas/unlisted-configuration', names)
        self.assertIn('nas/openclaw-backups/pre-2026.9.2-runtime/retained', names)
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
            self.assertEqual(retirement.archive(self.config, self.status_path, self.baseline_path, self.observed_path,
                                                self.archive_root), receipt)
        with (receipt.parent / 'legacy.tar.gz').open('ab') as damaged:
            damaged.write(b'truncated-or-changed')
        with self.assertRaises(ValueError):
            retirement.verify_archive(self.config, receipt)

    def test_restore_supports_reader_tarfile_without_filter_argument(self):
        extract = tarfile.TarFile.extract

        def reader_extract(tar, member, path='', set_attrs=True, *, numeric_owner=False):
            return extract(tar, member, path, set_attrs, numeric_owner=numeric_owner,
                           filter='data')

        with patch.object(tarfile.TarFile, 'extract', reader_extract), \
                patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
            receipt = retirement.archive(self.config, self.status_path,
                                         self.baseline_path, self.observed_path,
                                         self.archive_root)
            self.assertEqual(retirement.verify_archive(self.config, receipt)['format'], 1)

    def test_large_archive_verifies_without_caching_tar_members(self):
        retained = self.nas / 'openclaw'
        for number in range(4000):
            (retained / f'entry-{number:04d}').write_bytes(b'x')
        observed = retirement.inventory(self.config, self.status)
        self.observed_path.unlink()
        retirement.write_private(self.observed_path,
                                 dict(observed, rootIdentity=self.status['roots']))
        with patch.object(tarfile.TarFile, 'getmembers',
                          side_effect=AssertionError('tar headers cached in RAM')):
            with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
                receipt = retirement.archive(self.config, self.status_path,
                                             self.baseline_path, self.observed_path,
                                             self.archive_root)
            self.assertEqual(retirement.verify_archive(self.config, receipt)['format'], 1)

    def test_tree_walk_keeps_path_order_and_does_not_follow_links(self):
        (self.nas / 'prefix').mkdir()
        (self.nas / 'prefix' / 'child').write_bytes(b'x')
        (self.nas / 'prefix.sibling').write_bytes(b'y')
        (self.nas / 'external-link').symlink_to(self.local, target_is_directory=True)
        expected = [self.nas, *sorted(self.nas.rglob('*'))]
        self.assertEqual([path for path, _ in retirement.tree_paths(self.nas)], expected)

    def test_unreadable_empty_nas_file_keeps_mode_and_archive_entry(self):
        path = self.nas / 'unreadable-empty'
        path.touch()
        path.chmod(0)
        observed = retirement.inventory(self.config, self.status)
        self.observed_path.unlink()
        retirement.write_private(self.observed_path,
                                 dict(observed, rootIdentity=self.status['roots']))
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
            receipt = retirement.archive(self.config, self.status_path,
                                         self.baseline_path, self.observed_path,
                                         self.archive_root)
        with tarfile.open(receipt.parent / 'legacy.tar.gz', 'r:gz') as bundle:
            member = bundle.getmember('nas/unreadable-empty')
            self.assertEqual((member.size, member.mode), (0, 0))
        self.assertEqual(retirement.verify_archive(self.config, receipt)['format'], 1)

    def test_unreadable_nonempty_nas_file_still_blocks_inventory(self):
        path = self.nas / 'unreadable-nonempty'
        path.write_bytes(b'retained')
        path.chmod(0)
        with self.assertRaises(PermissionError):
            retirement.inventory(self.config, self.status)

    def test_restored_database_uses_archive_owner_not_original_source_owner(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
            receipt = retirement.archive(self.config, self.status_path,
                                         self.baseline_path, self.observed_path,
                                         self.archive_root)
        restored_config = dict(self.config, localUid=os.getuid() + 1)
        with self.assertRaises(ValueError):
            retirement.verify_read_only_database(
                self.local / self.config['requiredLocal'][0], restored_config)
        self.assertEqual(retirement.verify_archive(restored_config, receipt)['format'], 1)

    def test_symlink_targets_are_preserved_without_following_external_data(self):
        outside = self.archive_root / 'outside'
        outside.mkdir()
        sentinel = outside / 'sentinel'
        sentinel.write_text('untouched')
        links = {
            'external': str(outside),
            'absolute-contained': str(self.nas / 'unlisted-configuration'),
            'parent-contained': '../unlisted-configuration',
        }
        for name, target in links.items():
            (self.nas / 'openclaw' / name).symlink_to(target)
        os.link(self.nas / 'unlisted-configuration', self.nas / 'openclaw' / 'hardlink')
        observed = retirement.inventory(self.config, self.status)
        self.observed_path.unlink()
        retirement.write_private(self.observed_path,
                                 dict(observed, rootIdentity=self.status['roots']))
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
            receipt = retirement.archive(self.config, self.status_path,
                                         self.baseline_path, self.observed_path,
                                         self.archive_root)
        with tarfile.open(receipt.parent / 'legacy.tar.gz', 'r:gz') as bundle:
            names = set(bundle.getnames())
            for name, target in links.items():
                self.assertEqual(bundle.getmember(f'nas/openclaw/{name}').linkname, target)
            self.assertTrue(any(member.islnk() for member in bundle.getmembers()))
            self.assertNotIn('nas/openclaw/external/sentinel', names)
        self.assertEqual(retirement.verify_archive(self.config, receipt)['format'], 1)
        self.assertEqual(sentinel.read_text(), 'untouched')
        self.assertEqual(list(outside.iterdir()), [sentinel])

    def test_symlink_only_required_directory_restores(self):
        required = self.nas / 'openclaw'
        (required / 'retained').unlink()
        (required / 'only-link').symlink_to('/missing-external-target')
        observed = retirement.inventory(self.config, self.status)
        self.observed_path.unlink()
        retirement.write_private(self.observed_path,
                                 dict(observed, rootIdentity=self.status['roots']))
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
            receipt = retirement.archive(self.config, self.status_path,
                                         self.baseline_path, self.observed_path,
                                         self.archive_root)
        self.assertEqual(retirement.verify_archive(self.config, receipt)['format'], 1)

    def test_restore_rejects_duplicate_or_child_below_symlink(self):
        outside = self.archive_root / 'outside'
        outside.mkdir()
        for unsafe in ('duplicate', 'child'):
            with self.subTest(unsafe=unsafe):
                bundle = self.archive_root / f'{unsafe}.tar.gz'
                with tarfile.open(bundle, 'w:gz') as tar:
                    for root in ('local', 'nas'):
                        member = tarfile.TarInfo(root)
                        member.type = tarfile.DIRTYPE
                        tar.addfile(member)
                    link = tarfile.TarInfo('nas/external')
                    link.type = tarfile.SYMTYPE
                    link.linkname = str(outside)
                    tar.addfile(link)
                    if unsafe == 'duplicate':
                        tar.addfile(link)
                    else:
                        child = tarfile.TarInfo('nas/external/child')
                        child.size = 1
                        tar.addfile(child, io.BytesIO(b'x'))
                bundle.chmod(0o600)
                with patch.object(tarfile.TarFile, 'extract', side_effect=AssertionError('extracted')):
                    with self.assertRaisesRegex(ValueError, 'duplicate' if unsafe == 'duplicate'
                                                else 'unsafe member path'):
                        retirement.verify_bundle(bundle, retirement.digest(bundle), self.config,
                                                 self.observed['roots'])
                self.assertEqual(list(outside.iterdir()), [])

    def test_restore_rejects_hardlink_to_symlink_before_extraction(self):
        bundle = self.archive_root / 'hardlink-fallback.tar.gz'
        with tarfile.open(bundle, 'w:gz') as tar:
            for root in ('local', 'nas'):
                member = tarfile.TarInfo(root)
                member.type = tarfile.DIRTYPE
                tar.addfile(member)
            source = tarfile.TarInfo('nas/source-link')
            source.type = tarfile.SYMTYPE
            source.linkname = 'inside'
            tar.addfile(source)
            alias = tarfile.TarInfo('nas/alias')
            alias.type = tarfile.LNKTYPE
            alias.linkname = 'nas/source-link'
            tar.addfile(alias)
            injected = tarfile.TarInfo('nas/alias/injected')
            injected.size = 1
            tar.addfile(injected, io.BytesIO(b'x'))
        bundle.chmod(0o600)
        with patch.object(tarfile.TarFile, 'extract', side_effect=AssertionError('extracted')):
            with self.assertRaisesRegex(ValueError, 'unsafe hardlink'):
                retirement.verify_bundle(bundle, retirement.digest(bundle), self.config,
                                         self.observed['roots'])

    def test_archive_rejects_omitted_or_changed_unlisted_nas_file(self):
        original = retirement.add_tree
        for change in ('omitted', 'changed'):
            with self.subTest(change=change):
                def incomplete(tar, root, label):
                    if label != 'nas':
                        original(tar, root, label)
                    else:
                        tar.add(root, arcname=label, recursive=True,
                                filter=lambda member: None if member.name == 'nas/unlisted-configuration'
                                else member)
                        if change == 'changed':
                            member = tarfile.TarInfo('nas/unlisted-configuration')
                            member.size = len(b'changed')
                            tar.addfile(member, io.BytesIO(b'changed'))

                with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}), \
                     patch.object(retirement, 'add_tree', side_effect=incomplete):
                    with self.assertRaisesRegex(ValueError,
                                                'archive content differs from stopped source'):
                        retirement.archive(self.config, self.status_path, self.baseline_path,
                                           self.observed_path, self.archive_root)
                self.assertFalse(list(self.archive_root.glob('legacy-*/receipt.json')))

    def test_workflow_archive_writes_private_receipt_locator(self):
        config_path = self.archive_root / 'config.json'
        config_path.write_text(json.dumps({'legacyRetention': self.config}))
        result_path = self.archive_root / 'archive-result.json'
        result = subprocess.run([
            'python3', str(SOURCE), 'archive', '--config', str(config_path),
            '--status', str(self.status_path), '--baseline', str(self.baseline_path),
            '--observed', str(self.observed_path),
            '--destination', str(self.archive_root), '--output', str(result_path),
        ], env={**os.environ, 'GITHUB_ACTIONS': 'true'}, capture_output=True, text=True,
            timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = Path(json.loads(result_path.read_text())['receipt'])
        self.assertEqual(retirement.verify_archive(self.config, receipt)['format'], 1)
        self.assertEqual(stat.S_IMODE(result_path.stat().st_mode), 0o600)

    def test_writer_uncertainty_or_source_identity_change_never_publishes(self):
        for key, value in [('replicas', 1), ('pods', 1), ('activeJobs', 1),
                           ('cronJobSuspended', False), ('nodeReady', False),
                           ('node', 'other-node'), ('image', 'other-image'),
                           ('assistantSha256', 'other-hash'), ('claims', {}), ('roots', {}),
                           ('volumes', {}),
                           ('checkedAt', int(time.time()) - 121)]:
            with self.subTest(key=key):
                changed = dict(self.status, **{key: value})
                with self.assertRaises(ValueError):
                    retirement.stopped(changed, self.config, self.observed, self.baseline)
        with self.assertRaises(ValueError), patch.dict(os.environ, {}, clear=True):
            retirement.archive(self.config, self.status_path, self.baseline_path, self.observed_path,
                               self.archive_root)
        self.assertFalse(list(self.archive_root.glob('legacy-*/receipt.json')))

    def test_baseline_binds_pvc_and_pv_uids_before_shutdown(self):
        changed = json.loads(json.dumps(self.baseline))
        changed['kubernetes']['volumes']['openclaw-runtime-local']['pvUid'] = 'different-pv-uid'
        with self.assertRaises(ValueError):
            retirement.stopped(self.status, self.config, self.observed, changed)
        stale = dict(self.status, checkedAt=int(time.time()) - 121)
        with self.assertRaises(ValueError):
            retirement.inventory(self.config, stale)
        self.assertFalse(list(self.archive_root.glob('legacy-*/receipt.json')))

    def test_inventory_validates_status_before_long_scan(self):
        status = dict(self.status)
        scan = retirement.tree

        def long_scan(root):
            status['checkedAt'] = int(time.time()) - 121
            return scan(root)

        with patch.object(retirement, 'tree', side_effect=long_scan):
            self.assertEqual(retirement.inventory(self.config, status)['kubernetes'],
                             self.observed['kubernetes'])
        stale_path = self.archive_root / 'stale-status.json'
        retirement.write_private(stale_path, status)
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}), self.assertRaises(ValueError):
            retirement.archive(self.config, stale_path, self.baseline_path,
                               self.observed_path, self.archive_root)

    def test_scanned_inventory_uses_reader_owned_scratch(self):
        self.assertEqual(retirement.private_file(self.observed_path), self.observed_path)
        with self.assertRaises(ValueError):
            retirement.private_file(self.observed_path, os.getuid() + 1)

    def test_read_only_wal_is_verified_from_private_writable_snapshot(self):
        source = self.local / self.config['requiredLocal'][0]
        with closing(sqlite3.connect(source)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA wal_autocheckpoint=0')
            with db:
                db.execute('INSERT INTO messages (body) VALUES (?)', ('wal-row',))
            seen = []
            original = retirement.runtime_storage.verify_database

            def inspect_snapshot(path):
                self.assertTrue(path.resolve().is_relative_to(self.scratch_root.resolve()))
                with closing(sqlite3.connect(path)) as snapshot:
                    seen.append(snapshot.execute("SELECT count(*) FROM messages WHERE body='wal-row'").fetchone()[0])
                original(path)

            with patch.object(retirement.runtime_storage, 'verify_database', side_effect=inspect_snapshot):
                retirement.inventory(self.config, self.status)
            self.assertIn(1, seen)
        self.assertEqual(list(self.scratch_root.iterdir()), [])

    def test_archive_restores_committed_wal_without_writing_to_source(self):
        source = self.local / self.config['requiredLocal'][0]
        with closing(sqlite3.connect(source)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA wal_autocheckpoint=0')
            with db:
                db.execute('INSERT INTO messages (body) VALUES (?)', ('wal-row',))
            observed = retirement.inventory(self.config, self.status)
            self.observed_path.unlink()
            retirement.write_private(self.observed_path,
                                     dict(observed, rootIdentity=self.status['roots']))
            with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
                receipt = retirement.archive(self.config, self.status_path,
                                             self.baseline_path, self.observed_path,
                                             self.archive_root)
            with tarfile.open(receipt.parent / 'legacy.tar.gz', 'r:gz') as bundle:
                self.assertIn('local/state/openclaw.sqlite-wal', bundle.getnames())
            self.assertEqual(retirement.verify_archive(self.config, receipt)['format'], 1)
        self.assertEqual(list(self.scratch_root.iterdir()), [])

    def test_database_snapshot_refuses_untrusted_wal(self):
        source = self.local / self.config['requiredLocal'][0]
        wal = Path(str(source) + '-wal')
        wal.symlink_to(self.nas / 'unlisted-configuration')
        with self.assertRaises(ValueError):
            retirement.inventory(self.config, self.status)
        self.assertEqual(list(self.scratch_root.iterdir()), [])

    def test_missing_required_data_uid_and_overlap_fail_closed(self):
        for change in ('missing', 'uid', 'overlap'):
            with self.subTest(change=change):
                config = dict(self.config)
                if change == 'missing':
                    config['requiredNas'] = [*config['requiredNas'], 'missing-checkpoint']
                elif change == 'uid':
                    config['localUid'] = os.getuid() + 1
                else:
                    config['nasRoot'] = config['localRoot']
                with self.assertRaises(ValueError):
                    retirement.inventory(config)

    def test_unmatched_parent_child_mounts_are_rejected(self):
        wrong = self.nas / 'wrong'
        wrong.mkdir()
        config = dict(self.config, stateMount=str(wrong))
        with self.assertRaises(ValueError):
            retirement.inventory(config)

    def test_unsafe_paths_and_archive_corruption_fail_without_marker(self):
        config_path = self.archive_root / 'config.json'
        config_path.write_text(json.dumps({'legacyRetention': dict(self.config, requiredNas=['../escape'])}))
        with self.assertRaises(ValueError):
            retirement.config_at(config_path)
        (self.nas / 'openclaw' / 'escape').symlink_to('/private/unknown')
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
            with self.assertRaises(ValueError):
                retirement.archive(self.config, self.status_path, self.baseline_path, self.observed_path,
                                   self.archive_root)
        self.assertFalse(list(self.archive_root.glob('legacy-*/receipt.json')))

    def test_partial_failure_retains_private_diagnostics_without_marker(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}), \
             patch.object(retirement, 'add_tree', side_effect=ValueError('fixture failure')):
            with self.assertRaises(ValueError):
                retirement.archive(self.config, self.status_path, self.baseline_path, self.observed_path,
                                   self.archive_root)
        self.assertFalse(list(self.archive_root.glob('legacy-*/receipt.json')))
        pending = list(self.archive_root.glob('.partial-oce-legacy-*'))
        self.assertEqual(len(pending), 1)
        self.assertEqual(stat.S_IMODE(pending[0].stat().st_mode), 0o700)

    def test_partial_archive_and_private_diagnostics_cannot_verify(self):
        pending = self.archive_root / '.partial-oce-legacy-incomplete'
        pending.mkdir(mode=0o700)
        with self.assertRaises(FileNotFoundError):
            retirement.verify_archive(self.config, pending / 'receipt.json')
        public = self.archive_root / 'public.json'
        public.write_text('{}')
        public.chmod(0o644)
        with self.assertRaises(ValueError):
            retirement.private_file(public)

    def test_already_retired_cronjob_is_idempotent_but_unknown_job_is_not(self):
        retirement.stopped(dict(self.status, cronJobSuspended=False, cronJobAbsent=True),
                           self.config, self.observed, self.baseline)
        with self.assertRaises(ValueError):
            retirement.stopped(dict(self.status, activeJobs=None), self.config, self.observed,
                               self.baseline)


if __name__ == '__main__':
    unittest.main()
