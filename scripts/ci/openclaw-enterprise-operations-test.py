#!/usr/bin/env python3
"""Fail-closed local checks for the protected legacy archive lane."""

import os
import json
import hashlib
import subprocess
import tempfile
import unittest
import stat
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/ci/openclaw-enterprise-operations.sh'
WORKFLOW = ROOT / '.github/workflows/openclaw-enterprise-operations.yml'
WORKER = ROOT / 'scripts/ci/openclaw-legacy-inventory-worker.sh'


class Operations(unittest.TestCase):
    def test_inventory_worker_finishes_without_exec_stream_and_records_failure_privately(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            private.chmod(0o700)
            fake = private / 'fake.py'
            fake.write_text('''import os, pathlib, sys
output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
if os.environ.get('FAKE_FAIL'):
    print('private diagnostic')
    raise SystemExit(1)
output.write_text('verified')
''')
            worker = private / 'worker.sh'
            worker.write_text(WORKER.read_text().replace('/private/legacy', directory)
                              .replace('/etc/openclaw-retirement/retirement.py', str(fake)))
            for run_id, fail in (('101', False), ('102', True)):
                (private / 'inventory.lock').mkdir()
                result = subprocess.run(['sh', str(worker), run_id], cwd=ROOT,
                                        env={**os.environ, 'FAKE_FAIL': '1' if fail else ''},
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode == 0, not fail)
                self.assertEqual((private / f'inventory-{run_id}.state').read_text().strip(),
                                 'failure' if fail else 'success')
                self.assertEqual((private / f'baseline-{run_id}.json').exists(), not fail)
                self.assertFalse((private / 'inventory.lock').exists())
                self.assertEqual(stat.S_IMODE((private / f'inventory-{run_id}.log').stat().st_mode),
                                 0o600)
            self.assertIn('private diagnostic', (private / 'inventory-102.log').read_text())
            self.assertNotEqual(subprocess.run(['sh', str(worker), '../103'], cwd=ROOT,
                                               capture_output=True).returncode, 0)
            (private / 'inventory.lock').mkdir()
            (private / 'inventory-103.state').symlink_to(private / 'outside')
            self.assertNotEqual(subprocess.run(['sh', str(worker), '103'], cwd=ROOT,
                                               capture_output=True).returncode, 0)
            self.assertFalse((private / 'outside').exists())

    def test_private_directory_clears_inherited_setgid(self):
        command = "umask 077; mkdir -p /private/legacy; chmod 700 /private/legacy; chmod g-s /private/legacy"
        self.assertIn(command, SCRIPT.read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy'
            path.mkdir(mode=0o700)
            path.chmod(0o2700)
            subprocess.run(['sh', '-c', 'chmod 700 "$1"; chmod g-s "$1"', 'sh', str(path)],
                           check=True, capture_output=True)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)

    def test_reader_uses_the_reviewed_retirement_source(self):
        script = SCRIPT.read_text()
        self.assertIn('sha256sum clusters/homelab/apps/openclaw/retirement/retirement.py', script)
        self.assertIn('"${reader[@]}" sha256sum /etc/openclaw-retirement/retirement.py', script)

    def test_refresh_status_rechecks_writers_and_volume_identity(self):
        status = {'replicas': 0, 'readyReplicas': 0, 'pods': 0, 'activeJobs': 0,
                  'cronJobSuspended': True, 'readerPod': 'reader',
                  'readerPodUid': 'uid', 'claims': {'state': 'pvc'},
                  'volumes': {'state': {'pvUid': 'pv'}},
                  'roots': {'local': {'inode': 1}}}
        shell = '''set -euo pipefail
work="$1"
status_refresh_count=0
reader_input=(true)
python3() { cp "$TEST_STATUS" "${@: -1}"; }
source <(sed -n '/^refresh_status() {/,/^}/p' "$2")
refresh_status "$3"
'''
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'status.json').write_text(json.dumps(status))
            for changes, stage, expected in (({}, 'stopped', 0), ({'pods': 1}, 'stopped', 1),
                                             ({'pods': 1}, 'inventory', 0),
                                             ({'volumes': {'state': {'pvUid': 'changed'}}},
                                              'inventory', 1)):
                (work / 'next.json').write_text(json.dumps({**status, **changes}))
                result = subprocess.run(['bash', '-c', shell, 'bash', directory, str(SCRIPT), stage],
                                        cwd=ROOT, env={**os.environ, 'TEST_STATUS':
                                                       str(work / 'next.json')},
                                        capture_output=True, text=True, timeout=10,
                                        check=False)
                self.assertEqual(result.returncode == 0, expected == 0, result.stderr)

    def test_versioned_restore_streams_exact_bytes(self):
        payload = b'archive\x00bytes'

        class S3(BaseHTTPRequestHandler):
            def do_GET(self):
                self.server.paths.append(self.path)
                if self.server.fail:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        with HTTPServer(('127.0.0.1', 0), S3) as server, tempfile.TemporaryDirectory() as directory:
            server.paths = []
            server.fail = False
            Thread(target=server.serve_forever, daemon=True).start()
            destination = Path(directory) / 'archive'
            shell = '''set -euo pipefail
bucket=test
reader_input=()
if [[ "${TEST_READER_FAIL:-}" == true ]]; then reader_input=(false); fi
aws() { command aws --endpoint-url "$TEST_ENDPOINT" --no-sign-request "$@"; }
source <(sed -n '/^restore_version() (/,/^)/p' "$1")
restore_version key version-1 "$2"
'''
            try:
                result = subprocess.run(['bash', '-c', shell, 'bash', str(SCRIPT), str(destination)],
                                        cwd=ROOT, env={**os.environ, 'TEST_ENDPOINT':
                                                       f'http://127.0.0.1:{server.server_port}'},
                                        capture_output=True, timeout=20, check=False)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(destination.read_bytes(), payload)
                self.assertEqual(parse_qs(urlsplit(server.paths[0]).query),
                                 {'versionId': ['version-1']})
                server.fail = True
                result = subprocess.run(['bash', '-c', shell, 'bash', str(SCRIPT), str(destination)],
                                        cwd=ROOT, env={**os.environ, 'TEST_ENDPOINT':
                                                       f'http://127.0.0.1:{server.server_port}'},
                                        capture_output=True, timeout=20, check=False)
                self.assertNotEqual(result.returncode, 0)
                server.fail = False
                result = subprocess.run(['bash', '-c', shell, 'bash', str(SCRIPT), str(destination)],
                                        cwd=ROOT, env={**os.environ, 'TEST_READER_FAIL': 'true',
                                                       'TEST_ENDPOINT':
                                                       f'http://127.0.0.1:{server.server_port}'},
                                        capture_output=True, timeout=20, check=False)
                self.assertNotEqual(result.returncode, 0)
            finally:
                server.shutdown()

    def test_unreviewed_stage_or_receipt_reference_stops_before_credentials(self):
        base = {**os.environ, 'GITHUB_ACTIONS': 'true', 'GITHUB_SHA': 'a' * 40,
                'GITHUB_RUN_ID': '123'}
        for stage, extra in (
            ('arbitrary', {}), ('archive', {}), ('archive', {'BASELINE_REF': '../secret'}),
            ('verify', {}), ('verify', {'ARCHIVE_REF': 'abc/123'}),
        ):
            with self.subTest(stage=stage, extra=extra):
                result = subprocess.run(['bash', str(SCRIPT), stage], cwd=ROOT,
                                        env={**base, **extra}, capture_output=True,
                                        text=True, timeout=5, check=False)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('aws', result.stderr)
                self.assertNotIn('kubectl', result.stderr)

    def test_private_workflow_runs_only_fixed_stages_from_current_main(self):
        workflow = WORKFLOW.read_text()
        for required in (
            'options: [inventory, archive, verify]',
            'group: openclaw-enterprise-operations-production',
            'name: homelab-production',
            'test "$ACTUAL_SHA" = "$(gh api',
            'bash scripts/ci/install-kubeconfig.sh',
            'bash scripts/ci/openclaw-enterprise-operations.sh "$RUN_STAGE"',
            'private cluster and archive diagnostics withheld',
        ):
            self.assertIn(required, workflow)
        self.assertNotIn('actions/upload-artifact@', workflow)
        script = SCRIPT.read_text()
        self.assertIn(hashlib.sha256(WORKER.read_bytes()).hexdigest(), script)
        self.assertIn('nohup sh "$directory/inventory-worker-${run_id}.sh"', script)
        self.assertIn('mkdir "$directory/inventory.lock"', script)
        self.assertIn('/diagnostic.log" >/dev/null', script)


if __name__ == '__main__':
    unittest.main()
