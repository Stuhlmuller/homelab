#!/usr/bin/env python3
"""Exercise the dormant Dispatcharr paired-capture script with synthetic state."""
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'clusters/homelab/apps/dispatcharr/recovery-capture-candidate/capture.sh'
FENCE = 'a' * 40


class CaptureTests(unittest.TestCase):
    def test_candidate_is_excluded_and_fence_placeholder_is_fixed(self):
        app = ROOT / 'clusters/homelab/apps/dispatcharr'
        self.assertNotIn('recovery-capture-candidate',
                         (app / 'kustomization.yaml').read_text())
        self.assertIn('value: REPLACE_WITH_SIGNED_FENCE_COMMIT',
                      (app / 'recovery-capture-candidate/capture-job.yaml').read_text())

    def test_candidate_job_mounts_generated_configmap(self):
        candidate = ROOT / 'clusters/homelab/apps/dispatcharr/recovery-capture-candidate'
        rendered = subprocess.run(['kubectl', 'kustomize', str(candidate)],
                                  check=True, capture_output=True, text=True, timeout=20).stdout
        documents = rendered.split('---\n')
        configmap = next(item for item in documents if '\nkind: ConfigMap\n' in item)
        job = next(item for item in documents if '\nkind: Job\n' in item)
        name = next(line.removeprefix('  name: ') for line in configmap.splitlines()
                    if line.startswith('  name: '))
        self.assertIn('  namespace: media\n', configmap)
        self.assertIn('  namespace: media\n', job)
        self.assertIn('  suspend: true\n', job)
        self.assertRegex(job, rf'(?m)^\s+name: {re.escape(name)}\n\s+name: capture$')

    def test_candidate_uses_mirrored_active_postgres_digest(self):
        app = ROOT / 'clusters/homelab/apps/dispatcharr'
        active = (app / 'postgres-statefulset.yaml').read_text()
        pinned = re.findall(
            r'(?m)^\s+image: (harbor\.stinkyboi\.com/mirror/docker\.io/library/'
            r'postgres:17\.5-bookworm@sha256:[0-9a-f]{64})$', active)
        self.assertEqual(len(pinned), 2)
        self.assertEqual(pinned[0], pinned[1])
        rendered = subprocess.run(
            ['kubectl', 'kustomize', str(app / 'recovery-capture-candidate')],
            check=True, capture_output=True, text=True, timeout=20).stdout
        job = next(item for item in rendered.split('---\n') if '\nkind: Job\n' in item)
        self.assertIn(f'        image: {pinned[0]}\n', job)

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        root = Path(self.scratch.name)
        self.data = root / 'data'
        self.data.mkdir()
        (self.data / 'state.txt').write_text('synthetic Dispatcharr file')
        self.backup = root / 'backup'
        self.secret = root / 'password'
        self.secret.write_text('fixture-password')
        binary = root / 'bin'
        binary.mkdir()
        for name, source in {
            'pg_dumpall': '#!/bin/sh\nprintf "CREATE ROLE dispatcharr;\\n"\n',
            'pg_dump': '#!/bin/sh\nfor argument do case "$argument" in --file=*) file="${argument#--file=}";; esac; done\nprintf "synthetic custom dump" > "$file"\n',
            'pg_restore': '#!/bin/sh\ntest "$1" = --list && test -s "$2"\n',
        }.items():
            target = binary / name
            target.write_text(source)
            target.chmod(0o700)
        self.env = dict(os.environ)
        self.env.pop('PGPASSWORD', None)
        self.env.update({
            'PATH': f'{binary}:{self.env["PATH"]}',
            'CAPTURE_DATA_ROOT': str(self.data),
            'CAPTURE_BACKUP_ROOT': str(self.backup),
            'CAPTURE_SECRET_FILE': str(self.secret),
        })

    def capture(self, fence=FENCE):
        environment = dict(self.env, FENCE_REF=fence)
        return subprocess.run(['/bin/sh', str(SCRIPT)], env=environment,
                              text=True, capture_output=True, timeout=20)

    def test_candidate_capture_pairs_dump_data_without_fence_proof(self):
        result = self.capture()
        self.assertEqual(result.returncode, 0, result.stderr)
        completed = [path for path in self.backup.iterdir() if not path.name.startswith('.')]
        self.assertEqual(len(completed), 1)
        source = completed[0]
        self.assertEqual({path.name for path in source.iterdir()},
                         {'globals.sql', 'dispatcharr.dump', 'data.tar',
                          'capture.json', 'SHA256SUMS'})
        record = json.loads((source / 'capture.json').read_text())
        self.assertEqual(record['captured_at'], source.name)
        self.assertIs(record['writers_fenced'], False)
        self.assertEqual(record['requested_fence_reference'], FENCE)
        self.assertNotIn('approved_fence_reference', record)
        with tarfile.open(source / 'data.tar') as archive:
            self.assertEqual(archive.extractfile('./state.txt').read(),
                             b'synthetic Dispatcharr file')
        subprocess.run(['sha256sum', '--check', '--status', 'SHA256SUMS'],
                       cwd=source, check=True, timeout=10)

    def test_missing_fence_fails_before_creating_backup(self):
        result = self.capture('REPLACE_WITH_SIGNED_FENCE_COMMIT')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.backup.exists())

    def test_link_in_data_fails_without_completed_set(self):
        (self.data / 'escape').symlink_to('/etc/passwd')
        result = self.capture()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsupported link or special file', result.stderr)
        self.assertFalse(any(not path.name.startswith('.') for path in self.backup.iterdir()))


if __name__ == '__main__':
    unittest.main()
