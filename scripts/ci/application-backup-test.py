#!/usr/bin/env python3
"""Offline fault injection for the real application publication state machine."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('application_backup', Path(__file__).resolve().parents[1] / 'application-backup.py')
APP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APP)
SPEC = importlib.util.spec_from_file_location('application_backup_runner', Path(__file__).resolve().parents[1] / 'application-backup-run.py')
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class FakeAWS:
    def __init__(self):
        self.target = APP.target()
        self.objects = {}
        self.fail_key = None
        self.corrupt = False
        self.lose_ack = False
        self.wrong_version = False
        self.calls = []

    def check(self):
        pass

    def meta(self, version, data):
        return {'VersionId': version, 'ContentLength': len(data),
                'ChecksumSHA256': APP.OFFSITE.checksum({'sha256': hashlib.sha256(data).hexdigest()}),
                'ServerSideEncryption': 'aws:kms', 'BucketKeyEnabled': True}

    def call(self, service, operation, args=(), missing=False):
        self.calls.append(operation)
        assert service == 's3api'
        if operation == 'list-objects-v2':
            prefix = args[args.index('--prefix') + 1]
            return {'Contents': [{'Key': key} for key in self.objects if key.startswith(prefix)]}
        key = args[args.index('--key') + 1]
        if key.endswith(self.fail_key or '/impossible'):
            raise ValueError('injected failure')
        if operation == 'put-object':
            assert args[args.index('--if-none-match') + 1] == '*'
            assert key not in self.objects
            data = Path(args[args.index('--body') + 1]).read_bytes()
            assert args[args.index('--checksum-sha256') + 1] == self.meta('v', data)['ChecksumSHA256']
            version = f'v{len(self.objects)}'
            self.objects[key] = (version, data)
            if self.lose_ack:
                self.lose_ack = False
                raise ValueError('lost PUT response')
            return self.meta(version, data)
        if key not in self.objects:
            if missing:
                return None
            raise ValueError('missing remote object')
        version, data = self.objects[key]
        if '--version-id' in args:
            assert args[args.index('--version-id') + 1] == version
        if operation == 'get-object':
            assert '--version-id' in args
            Path(args[-1]).write_bytes(b'corrupt' if self.corrupt else data)
        elif operation != 'head-object':
            raise AssertionError(operation)
        return self.meta('wrong-version' if self.wrong_version else version, data)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.workspace = self.root / 'private'
        self.workspace.mkdir(mode=0o700)
        self.source = self.root / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.source.mkdir()
        self.make_source('octelium')
        self.aws = FakeAWS()

    def make_source(self, app):
        sums = []
        for name in APP.CONTRACTS[app]:
            data = b'synthetic fixture: ' + name.encode()
            (self.source / name).write_bytes(data)
            sums.append(f'{hashlib.sha256(data).hexdigest()}  {name}\n')
        (self.source / 'SHA256SUMS').write_text(''.join(sums))

    def prepare(self, app='octelium'):
        return APP.prepare(self.source, self.workspace, app)

    def test_remote_only_retrieval_and_resumable_success(self):
        prepared = self.prepare()
        identifier = APP.publish(prepared, self.workspace, self.aws)
        APP.publish(prepared, self.workspace, self.aws)
        self.assertEqual(len(self.aws.objects), 3)
        # Retrieval needs only the app and remote identifier; no local receipt.
        (prepared / 'publication.json').unlink()
        recovered = APP.retrieve('octelium', identifier, self.workspace, self.aws)
        self.assertEqual((recovered / 'octelium.dump').read_bytes(), (self.source / 'octelium.dump').read_bytes())
        self.assertEqual(APP.completed(self.aws, 'octelium'), [identifier])
        self.assertFalse(json.loads((recovered / 'retrieval.json').read_text())['application_restore_tested'])

    def test_partial_upload_never_completes_then_retries(self):
        prepared = self.prepare()
        self.aws.fail_key = '/octelium.dump'
        with self.assertRaises(ValueError):
            APP.publish(prepared, self.workspace, self.aws)
        self.assertEqual(APP.completed(self.aws, 'octelium'), [])
        self.aws.fail_key = None
        APP.publish(prepared, self.workspace, self.aws)
        self.assertEqual(len(self.aws.objects), 3)

    def test_lost_upload_ack_resumes_without_overwrite(self):
        prepared = self.prepare()
        self.aws.lose_ack = True
        with self.assertRaises(ValueError):
            APP.publish(prepared, self.workspace, self.aws)
        APP.publish(prepared, self.workspace, self.aws)
        self.assertEqual(len(self.aws.objects), 3)

    def test_download_corruption_blocks_completion(self):
        prepared = self.prepare()
        self.aws.corrupt = True
        with self.assertRaises(ValueError):
            APP.publish(prepared, self.workspace, self.aws)
        self.assertEqual(APP.completed(self.aws, 'octelium'), [])

    def test_completion_marker_failure_is_resumable(self):
        prepared = self.prepare()
        self.aws.fail_key = '/complete.json'
        with self.assertRaises(ValueError):
            APP.publish(prepared, self.workspace, self.aws)
        self.assertEqual(APP.completed(self.aws, 'octelium'), [])
        self.aws.fail_key = None
        APP.publish(prepared, self.workspace, self.aws)

    def test_wrong_version_blocks_retrieval(self):
        prepared = self.prepare()
        APP.publish(prepared, self.workspace, self.aws)
        self.aws.wrong_version = True
        with self.assertRaises((ValueError, AssertionError)):
            APP.retrieve('octelium', prepared.name, self.workspace, self.aws)

    def test_source_checksum_failure_and_partial_set(self):
        (self.source / 'octelium.dump').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.prepare()
        self.make_source('octelium')
        (self.source / 'globals.sql').unlink()
        with self.assertRaises(OSError):
            self.prepare()

    def test_no_symlink_or_checksum_path_escape(self):
        (self.source / 'octelium.dump').unlink()
        (self.source / 'octelium.dump').symlink_to(self.source / 'globals.sql')
        with self.assertRaises(ValueError):
            self.prepare()
        (self.source / 'SHA256SUMS').write_text('0' * 64 + '  ../private\n')
        with self.assertRaises(ValueError):
            self.prepare()

    def test_changed_preparation_rejected(self):
        prepared = self.prepare()
        (prepared / 'octelium.dump').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            APP.publish(prepared, self.workspace, self.aws)
        self.assertEqual(self.aws.objects, {})

    def test_stale_and_future_source_not_refreshed_by_upload(self):
        for hours in (31, -1):
            with patch.object(APP, 'now', return_value=APP.captured(self.source.name) + hours * 3600):
                with self.assertRaises(ValueError):
                    self.prepare()

    def test_paired_sets_require_matching_capture_fence(self):
        self.make_source('multica')
        with self.assertRaises(ValueError):
            self.prepare('multica')
        capture = {'captured_at': self.source.name, 'writers_fenced': True,
                   'approved_fence_reference': 'fixture-only-fence'}
        for fenced in (False, True):
            capture['writers_fenced'] = fenced
            (self.source / 'capture.json').write_text(json.dumps(capture))
            (self.source / 'SHA256SUMS').write_text(''.join(
                f'{hashlib.sha256((self.source / name).read_bytes()).hexdigest()}  {name}\n'
                for name in APP.CONTRACTS['multica']))
            if not fenced:
                with self.assertRaises(ValueError):
                    self.prepare('multica')
            else:
                prepared = self.prepare('multica')
                APP.publish(prepared, self.workspace, self.aws)
                self.assertEqual(len(self.aws.objects), 5)

    def test_all_six_media_databases_required(self):
        self.make_source('media-postgres')
        prepared = self.prepare('media-postgres')
        APP.publish(prepared, self.workspace, self.aws)
        recovered = APP.retrieve('media-postgres', prepared.name, self.workspace, self.aws)
        self.assertTrue(all((recovered / name).exists() for name in APP.CONTRACTS['media-postgres']))
        self.assertEqual(len(self.aws.objects), 8)

    def test_retention_protects_last_seven_and_never_deletes(self):
        identifiers = [f'202601{day:02}T000000Z-' + 'a' * 64 for day in range(1, 12)]
        self.assertEqual(APP.retention_plan(identifiers, APP.captured('20260112T000000Z')), [])
        self.assertEqual(APP.retention_plan(identifiers, APP.captured('20260301T000000Z')), identifiers[:4])
        self.assertEqual(APP.retention_plan(identifiers[:3], APP.captured('20260301T000000Z')), [])
        self.assertFalse(any('delete' in call for call in self.aws.calls))

    def test_failure_metrics_cannot_report_fresh_success(self):
        output = self.root / 'application.prom'
        APP.metrics(output, 'octelium', False)
        self.assertIn('check_success{app="octelium"} 0', output.read_text())
        self.assertIn('capture_timestamp_seconds{app="octelium"} 0', output.read_text())

    def test_metrics_recover_after_interruption(self):
        output = self.root / 'application.prom'
        APP.metrics(output, 'octelium', True, 123)
        previous = output.read_bytes()
        output.with_name(output.name + '.partial').write_text('interrupted old write')
        write = APP.write

        def interrupted(path, data):
            write(path, data)
            raise OSError('interrupted metrics write')

        with patch.object(APP, 'write', side_effect=interrupted), self.assertRaises(OSError):
            APP.metrics(output, 'octelium', False)
        self.assertEqual(output.read_bytes(), previous)
        APP.metrics(output, 'octelium', False)
        self.assertIn('check_success{app="octelium"} 0', output.read_text())
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.root.glob('.application.prom-*')), [])

    def test_hourly_runner_publishes_both_apps_and_continues_after_failure(self):
        media_root = self.root / 'media-source'
        media_source = media_root / self.source.name
        media_source.mkdir(parents=True)
        with patch.object(self, 'source', media_source):
            self.make_source('media-postgres')
        metrics = self.root / 'metrics'
        metrics.mkdir()
        config = self.root / 'recovery/application-backups/schedule.json'
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({
            'workspace': str(self.workspace), 'metrics_directory': str(metrics),
            'aws_cli': '/fixture/aws', 'profile': 'fixture',
            'source_roots': {'octelium': str(self.root), 'media-postgres': str(media_root)},
        }))
        for app in APP.CONTRACTS:
            (self.workspace / app).mkdir(mode=0o700)
        with (patch.object(RUNNER, 'ROOT', self.root), patch.object(RUNNER, 'APP', APP),
              patch.object(RUNNER.shutil, 'disk_usage', return_value=SimpleNamespace(free=25 * 1024**3)),
              patch.object(APP.OFFSITE, 'AWS', return_value=self.aws)):
            for fail_key in (None, '/octelium.dump'):
                with self.subTest(fail_key=fail_key):
                    self.aws.fail_key = fail_key
                    self.assertEqual(RUNNER.main(), int(fail_key is not None))
                    self.assertIn('check_success{app="media-postgres"} 1',
                                  (metrics / 'media-postgres.prom').read_text())
                    self.assertIn(f'check_success{{app="octelium"}} {int(fail_key is None)}',
                                  (metrics / 'octelium.prom').read_text())
        self.assertEqual(len(self.aws.objects), 11)


if __name__ == '__main__':
    unittest.main()
