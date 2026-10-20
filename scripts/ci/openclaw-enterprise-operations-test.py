#!/usr/bin/env python3
"""Fail-closed local checks for protected OpenClaw operations."""

import os
import json
import hashlib
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
import stat
import textwrap
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from unittest import mock
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/ci/openclaw-enterprise-operations.sh'
UPLOAD = ROOT / 'scripts/ci/openclaw-enterprise-upload.py'
ENTERPRISE_SCRIPT = ROOT / 'scripts/ci/openclaw-enterprise-stage.sh'
BINDER = ROOT / 'scripts/openclaw-enterprise-bind-installation.py'
BINDER_SHA256 = 'fedf388eaee3a30d53858e2e5141b6ed737307c7e9f8e7a0008588056a136996'
WORKFLOW = ROOT / '.github/workflows/openclaw-enterprise-operations.yml'
WORKER = ROOT / 'clusters/homelab/apps/openclaw/retirement/inventory-worker.sh'
ROLE = ROOT / 'IaC/terragrunt-catalog/modules/aws-github-actions-role-policy/main.tf'


class Operations(unittest.TestCase):
    def test_bounded_reader_refuses_changed_size_and_symlink(self):
        reader = runpy.run_path(str(UPLOAD))['RANGE_READ']
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'archive'
            source.write_bytes(b'abcdefghij')
            command = ['python3', '-c', reader, str(source), '3', '4', '10']
            result = subprocess.run(command, capture_output=True, timeout=5, check=False)
            self.assertEqual((result.returncode, result.stdout), (0, b'defg'))
            for changed_size, symlink in ((True, False), (False, True)):
                path = source
                if symlink:
                    path = Path(directory) / 'alias'
                    path.symlink_to(source)
                result = subprocess.run(['python3', '-c', reader, str(path), '3', '4',
                                         '11' if changed_size else '10'],
                                        capture_output=True, timeout=5, check=False)
                self.assertNotEqual(result.returncode, 0)

    def test_archive_upload_completes_only_after_full_size_and_digest(self):
        payload = b'verified archive bytes'
        with tempfile.TemporaryDirectory() as directory:
            fake_aws = Path(directory) / 'aws'
            fake_kubectl = Path(directory) / 'kubectl'
            log = Path(directory) / 'aws.jsonl'
            kube_log = Path(directory) / 'kubectl.log'
            source = Path(directory) / 'source'
            truncated_once = Path(directory) / 'truncated-once'
            fake_aws.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
operation = args[1]
log = pathlib.Path(os.environ['FAKE_AWS_LOG'])
with log.open('a') as output:
    output.write(json.dumps({'operation': operation,
                             'size': pathlib.Path(args[args.index('--body') + 1]).stat().st_size
                             if '--body' in args else None}) + '\\n')
if operation == 'create-multipart-upload':
    if operation == os.environ.get('FAKE_AWS_FAIL'):
        raise SystemExit(7)
    print(json.dumps({'UploadId': 'test-upload'}))
elif operation == 'upload-part':
    if operation == os.environ.get('FAKE_AWS_FAIL'):
        raise SystemExit(7)
    print(json.dumps({'ETag': '"test-etag"'}))
elif operation == 'complete-multipart-upload':
    if operation == os.environ.get('FAKE_AWS_FAIL'):
        raise SystemExit(7)
    manifest = pathlib.Path(args[args.index('--multipart-upload') + 1][7:])
    assert json.loads(manifest.read_text())['Parts'] == [
        {'ETag': '"test-etag"', 'PartNumber': 1}]
    print('{}')
elif operation == 'abort-multipart-upload':
    print('{}')
else:
    raise SystemExit(2)
''')
            fake_aws.chmod(0o755)
            fake_kubectl.write_text('''#!/usr/bin/env python3
import os, pathlib, sys
args = sys.argv[1:]
assert args[:7] == ['-n', 'ai', 'exec', 'openclaw-retirement-reader-test', '-c', 'reader', '--']
assert args[7:10] == ['python3', '-c', args[9]]
assert args[10] == '/archive/private/legacy-' + 'a' * 64 + '/legacy.tar.gz'
offset, count, expected_size = map(int, args[11:14])
source = pathlib.Path(os.environ['FAKE_SOURCE']).read_bytes()
with pathlib.Path(os.environ['FAKE_KUBECTL_LOG']).open('a') as output:
    output.write(f'{offset}:{count}\\n')
if len(source) != expected_size:
    raise SystemExit(2)
chunk = source[offset:offset + count]
marker = pathlib.Path(os.environ['FAKE_TRUNCATE_ONCE'])
if marker.exists():
    marker.unlink()
    chunk = chunk[:8]
sys.stdout.buffer.write(chunk)
''')
            fake_kubectl.chmod(0o755)
            digest = hashlib.sha256(payload).hexdigest()
            env = {**os.environ, 'PATH': directory + os.pathsep + os.environ['PATH'],
                   'FAKE_AWS_LOG': str(log), 'FAKE_SOURCE': str(source),
                   'FAKE_KUBECTL_LOG': str(kube_log),
                   'FAKE_TRUNCATE_ONCE': str(truncated_once)}
            for body, size, expected_digest, flaky, aws_fail, code in (
                    (payload[:8], len(payload), digest, False, '', 10),
                    (payload, len(payload), '0' * 64, False, '', 14),
                    (payload + b'extra', len(payload), digest, False, '', 10),
                    (payload, len(payload), digest, False, '', 0),
                    (payload, len(payload), digest, True, '', 0),
                    (payload, len(payload), digest, False, 'create-multipart-upload', 11),
                    (payload, len(payload), digest, False, 'upload-part', 12),
                    (payload, len(payload), digest, False, 'complete-multipart-upload', 13)):
                log.unlink(missing_ok=True)
                kube_log.unlink(missing_ok=True)
                source.write_bytes(body)
                if flaky:
                    truncated_once.touch()
                result = subprocess.run(['python3', '-I', str(UPLOAD), 'bucket', 'key',
                                         str(size), expected_digest,
                                         'openclaw-retirement-reader-test',
                                         '/archive/private/legacy-' + 'a' * 64 + '/legacy.tar.gz'],
                                        cwd=ROOT, env={**env, 'FAKE_AWS_FAIL': aws_fail}, capture_output=True,
                                        timeout=10, check=False)
                self.assertEqual(result.returncode, code, result.stderr)
                operations = [json.loads(line)['operation'] for line in log.read_text().splitlines()]
                self.assertEqual('complete-multipart-upload' in operations, code in (0, 13))
                self.assertEqual('abort-multipart-upload' in operations, code not in (0, 11))
                self.assertEqual(len(kube_log.read_text().splitlines()) if kube_log.exists() else 0,
                                 0 if code == 11 else 2 if flaky else 3 if len(body) != size else 1)

    def test_archive_upload_assembles_parts_from_smaller_reads_and_aborts_on_truncation(self):
        module = runpy.run_path(str(UPLOAD))
        self.assertEqual(module['PART_SIZE'], 64 * 1024 * 1024)
        self.assertEqual(module['READ_SIZE'], 8 * 1024 * 1024)
        main = module['main']
        payload = b'abcdefghijklmnopqrstuv'
        arguments = ['upload', 'bucket', 'key', str(len(payload)),
                     hashlib.sha256(payload).hexdigest(), 'openclaw-retirement-reader-test',
                     '/archive/private/legacy-' + 'a' * 64 + '/legacy.tar.gz']
        for truncated in (False, True):
            reads, uploads, operations = [], [], []

            def fake_source_range(_pod, _path, offset, count, expected_size):
                self.assertEqual(expected_size, len(payload))
                reads.append((offset, count))
                return payload[offset:offset + count - (1 if truncated and offset == 6 else 0)]

            def fake_aws(*args):
                operation = args[0]
                operations.append(operation)
                if operation == 'create-multipart-upload':
                    return '{"UploadId":"test-upload"}'
                if operation == 'upload-part':
                    uploads.append(Path(args[args.index('--body') + 1]).read_bytes())
                    return '{"ETag":"test-etag"}'
                if operation == 'complete-multipart-upload':
                    manifest = Path(args[args.index('--multipart-upload') + 1][7:])
                    self.assertEqual(len(json.loads(manifest.read_text())['Parts']), 2)
                return '{}'

            with mock.patch.dict(main.__globals__, {'PART_SIZE': 16, 'READ_SIZE': 6,
                                                      'source_range': fake_source_range,
                                                      'aws': fake_aws}), mock.patch.object(sys, 'argv', arguments):
                if truncated:
                    with self.assertRaises(module['RangeReadError']):
                        main()
                else:
                    main()
            self.assertEqual(reads, [(0, 6), (6, 6), (12, 4)] if truncated else
                             [(0, 6), (6, 6), (12, 4), (16, 6)])
            self.assertEqual(uploads, [] if truncated else [payload[:16], payload[16:]])
            self.assertEqual(operations[-1], 'abort-multipart-upload' if truncated else
                             'complete-multipart-upload')

    def test_legacy_session_outlives_the_bounded_job(self):
        workflow = WORKFLOW.read_text().split('\n  legacy:\n', 1)[1].split('\n  enterprise:\n', 1)[0]
        role = ROLE.read_text()
        requested = re.findall(r'^\s+role-duration-seconds: (\d+)$', workflow, re.M)
        maximum = re.findall(r'^\s+max_session_duration = (\d+)\b', role, re.M)
        limit = re.findall(r'^    timeout-minutes: (\d+)$', workflow, re.M)
        self.assertEqual(requested, ['25200'])
        self.assertEqual(maximum, requested)
        self.assertEqual(limit, ['360'])
        self.assertGreaterEqual(int(requested[0]) - 60 * int(limit[0]), 3600)
    def test_enterprise_stages_are_pinned_serialized_and_fail_closed(self):
        workflow = WORKFLOW.read_text()
        script = ENTERPRISE_SCRIPT.read_text()
        digest = hashlib.sha256(ENTERPRISE_SCRIPT.read_bytes()).hexdigest()
        self.assertIn(f"{digest}  scripts/ci/openclaw-enterprise-stage.sh", workflow)
        self.assertIn('options: [none, bind-installation, full-sync, reconcile, stop, verification, '
                      'restore, acceptance]', workflow)
        self.assertIn('Choose exactly one fixed operation stage.', workflow)
        self.assertEqual(workflow.count('group: openclaw-enterprise-operations-production'), 3)
        self.assertEqual(workflow.count('queue: max'), 3)
        self.assertIn("inputs.legacy_stage != 'none' && inputs.enterprise_stage == 'none'",
                      workflow)
        self.assertIn("inputs.legacy_stage == 'none' && inputs.enterprise_stage != 'none' && "
                      "inputs.enterprise_stage != 'bind-installation'",
                      workflow)
        self.assertIn('private diagnostics withheld', workflow)
        self.assertIn('durable private journal runner is not declared', script)
        self.assertNotIn('kubectl', script)
        self.assertNotIn('argocd', script)
        self.assertNotIn('openclaw-enterprise.py', script)

        enterprise_job = workflow.split('\n  enterprise:\n', 1)[1]
        self.assertLess(enterprise_job.index('name: Check Out Repository'),
                        enterprise_job.index('name: Recheck Current Main Commit Before Enterprise Stage'))
        self.assertLess(enterprise_job.index('name: Recheck Current Main Commit Before Enterprise Stage'),
                        enterprise_job.index('name: Run Fixed Enterprise Stage'))
        recheck = re.search(r'      - name: Recheck Current Main Commit Before Enterprise Stage\n'
                            r'.*?        run: \|\n'
                            r'(.*?)(?=\n      - name: Run Fixed Enterprise Stage)',
                            enterprise_job, re.S)
        self.assertIsNotNone(recheck)
        with tempfile.TemporaryDirectory() as directory:
            fake_gh = Path(directory) / 'gh'
            fake_gh.write_text('#!/bin/sh\nprintf "%s\\n" "$FAKE_MAIN_SHA"\n')
            fake_gh.chmod(0o755)
            for current_main, expected in (('a' * 40, True), ('b' * 40, False)):
                result = subprocess.run(['bash', '-c', textwrap.dedent(recheck.group(1))],
                                        cwd=ROOT, env={**os.environ,
                                                       'PATH': f'{directory}:{os.environ["PATH"]}',
                                                       'ACTUAL_REF': 'refs/heads/main',
                                                       'ACTUAL_SHA': 'a' * 40,
                                                       'EXPECTED_SHA': 'a' * 40,
                                                       'FAKE_MAIN_SHA': current_main,
                                                       'GH_REPO': 'Stuhlmuller/homelab',
                                                       'GH_TOKEN': 'test'},
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode == 0, expected,
                                 (current_main, result.stderr))

        dispatch = re.search(r'      - name: Verify Dispatch Commit\n.*?        run: \|\n'
                             r'(.*?)(?=\n      - name: Check Out Repository)',
                             workflow, re.S)
        self.assertIsNotNone(dispatch)
        guard = textwrap.dedent(dispatch.group(1))
        base = {**os.environ, 'ACTUAL_REF': 'refs/heads/main',
                'ACTUAL_SHA': 'a' * 40, 'EXPECTED_SHA': 'a' * 40,
                'BASELINE_REF': '', 'ARCHIVE_REF': ''}
        for legacy, enterprise, baseline, expected in (
            ('inventory', 'none', '', True), ('none', 'verification', '', True),
            ('none', 'bind-installation', '', True),
            ('none', 'none', '', False), ('inventory', 'stop', '', False),
            ('none', 'reconcile', 'unexpected', False),
        ):
            result = subprocess.run(['bash', '-c', guard], cwd=ROOT,
                                    env={**base, 'LEGACY_STAGE': legacy,
                                         'ENTERPRISE_STAGE': enterprise,
                                         'BASELINE_REF': baseline},
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode == 0, expected,
                             (legacy, enterprise, result.stderr))

        sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                      text=True).strip()
        run_env = {**os.environ, 'GITHUB_ACTIONS': 'true', 'GITHUB_SHA': sha,
                   'EXPECTED_SHA': sha}
        for stage in ('full-sync', 'reconcile', 'stop', 'verification',
                      'restore', 'acceptance'):
            with self.subTest(stage=stage):
                result = subprocess.run(['bash', str(ENTERPRISE_SCRIPT), stage], cwd=ROOT,
                                        env=run_env, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('durable private journal runner is not declared', result.stderr)
        for stage in ('', 'inventory', 'unknown', '../restore'):
            with self.subTest(stage=stage):
                result = subprocess.run(['bash', str(ENTERPRISE_SCRIPT), stage], cwd=ROOT,
                                        env=run_env, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2)
        stale = subprocess.run(['bash', str(ENTERPRISE_SCRIPT), 'verification'], cwd=ROOT,
                               env={**run_env, 'EXPECTED_SHA': '0' * 40},
                               capture_output=True, text=True, timeout=5)
        self.assertEqual(stale.returncode, 2)

    def test_installation_binding_is_pinned_protected_and_requires_private_file(self):
        workflow = WORKFLOW.read_text()
        binding = workflow.split('\n  binding:\n', 1)[1]
        self.assertIn("inputs.enterprise_stage == 'bind-installation'", binding)
        self.assertIn('name: homelab-production', binding)
        self.assertIn('group: openclaw-enterprise-operations-production', binding)
        self.assertIn('queue: max', binding)
        self.assertIn('OCTELIUM_AUTH_TOKEN: ${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}', binding)
        self.assertNotIn('id-token: write', binding)
        self.assertLess(binding.index('name: Recheck Current Main Commit Before Binding'),
                        binding.index('name: Bind Reviewed Installation'))
        self.assertIn('test "$ACTUAL_SHA" = "$(gh api', binding)
        self.assertIn(f'{BINDER_SHA256}  scripts/openclaw-enterprise-bind-installation.py',
                      binding)
        if BINDER.exists():
            self.assertEqual(hashlib.sha256(BINDER.read_bytes()).hexdigest(), BINDER_SHA256)
        self.assertIn('test "$(jq -r \'.bootstrap.serviceKeyFile // empty\' '
                      'scripts/config/openclaw-enterprise.json)" = '
                      '/private/openclaw-enterprise/bootstrap/initial-admin-service-key.json',
                      binding)
        self.assertIn('test -f /private/openclaw-enterprise/bootstrap/'
                      'initial-admin-service-key.json', binding)
        self.assertIn("stat -c '%u:%a' /private/openclaw-enterprise/bootstrap/"
                      'initial-admin-service-key.json', binding)
        self.assertIn("timeout 10m nix develop --command bash <<'EOF'", binding)
        self.assertIn('ulimit -f 1024', binding)
        self.assertIn('private diagnostics withheld', binding)
        self.assertNotIn('cat "$private_log"', binding)

        run = textwrap.dedent(binding.split('        run: |\n')[-1])
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory)
            (fake / 'sha256sum').write_text('#!/bin/sh\nexit 0\n')
            (fake / 'jq').write_text(
                '#!/bin/sh\nprintf "%s\\n" '
                '"/private/openclaw-enterprise/bootstrap/initial-admin-service-key.json"\n')
            marker = fake / 'ran-binder'
            (fake / 'timeout').write_text(
                '#!/bin/sh\ntouch "$BINDER_MARKER"\nexit 0\n')
            (fake / 'stat').write_text('#!/bin/sh\nprintf "0:644\\n"\n')
            (fake / 'id').write_text('#!/bin/sh\nprintf "0\\n"\n')
            for name in ('sha256sum', 'jq', 'timeout', 'stat', 'id'):
                (fake / name).chmod(0o755)
            # Reject a missing key and an existing key with weak file mode.
            for gate, file_tests in (
                    ('missing', 'return 1'),
                    ('weak_mode', 'return 0')):
                with self.subTest(gate=gate):
                    private_file = ('test() { if [[ "$1" == -f || "$1" == -s ]]; '
                                    f'then {file_tests}; else builtin test "$@"; fi; }}\n')
                    result = subprocess.run(['bash', '-c', private_file + run], cwd=ROOT,
                                            env={**os.environ,
                                                 'PATH': f'{fake}:{os.environ["PATH"]}',
                                                 'OCTELIUM_AUTH_TOKEN': 'test',
                                                 'EXPECTED_SHA': 'a' * 40,
                                                 'BINDER_MARKER': str(marker)},
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stdout.strip(),
                                     '::error::Enterprise Installation binding blocked; '
                                     'private diagnostics withheld.')
                    self.assertFalse(marker.exists())

    def test_workflow_pins_current_operations_script(self):
        pins = re.findall(
            r"sha256sum --check --status <<<'([0-9a-f]{64})  scripts/ci/openclaw-enterprise-operations\.sh'",
            WORKFLOW.read_text(),
        )
        self.assertEqual(pins, [hashlib.sha256(SCRIPT.read_bytes()).hexdigest()])
        upload_pins = re.findall(
            r"sha256sum --check --status <<<'([0-9a-f]{64})  scripts/ci/openclaw-enterprise-upload\.py'",
            WORKFLOW.read_text(),
        )
        self.assertEqual(upload_pins, [hashlib.sha256(UPLOAD.read_bytes()).hexdigest()])

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
            ('arbitrary', {}), ('publish-inventory', {}),
            ('publish-inventory', {'BASELINE_REF': 'a' * 39 + '/39127113354'}),
            ('publish-inventory', {'BASELINE_REF': 'a' * 40 + '/../secret'}),
            ('archive', {}), ('archive', {'BASELINE_REF': '../secret'}),
            ('publish-archive', {}),
            ('publish-archive', {'BASELINE_REF': 'a' * 40 + '/123', 'ARCHIVE_REF': '../secret'}),
            ('verify', {}), ('verify', {'ARCHIVE_REF': 'abc/123'}),
        ):
            with self.subTest(stage=stage, extra=extra):
                result = subprocess.run(['bash', str(SCRIPT), stage], cwd=ROOT,
                                        env={**base, **extra}, capture_output=True,
                                        text=True, timeout=5, check=False)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('aws', result.stderr)
                self.assertNotIn('kubectl', result.stderr)

        with tempfile.TemporaryDirectory() as directory:
            aws = Path(directory) / 'aws'
            called = Path(directory) / 'called'
            aws.write_text('#!/bin/sh\ntouch "$AWS_CALLED"\nexit 1\n')
            aws.chmod(0o755)
            result = subprocess.run(['bash', str(SCRIPT), 'publish-inventory'], cwd=ROOT,
                                    env={**base, 'BASELINE_REF': 'a' * 40 + '/39157724373',
                                         'AWS_CALLED': str(called),
                                         'PATH': directory + os.pathsep + os.environ['PATH']},
                                    capture_output=True, text=True, timeout=5, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertTrue(called.exists())

    def test_failure_reports_only_fixed_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            phase = Path(directory) / 'phase'
            result = subprocess.run(['bash', str(SCRIPT), 'invalid'], cwd=ROOT,
                                    env={**os.environ, 'OPENCLAW_PHASE_FILE': str(phase)},
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(phase.exists())
            workflow = WORKFLOW.read_text()
            self.assertIn('preflight|baseline|publication|publication-lookup|'
                          'publication-lookup-denied|publication-lookup-failed|'
                          'publication-lookup-response|publication-upload|'
                          'publication-source-read|publication-s3-create|publication-s3-part|'
                          'publication-s3-complete|publication-digest|'
                          'publication-version|verification', workflow)
            script = SCRIPT.read_text()
            self.assertIn('phase=publication-lookup\n    lookup_baseline_versions', script)
            self.assertIn('list-object-versions --no-paginate --bucket "$bucket" --prefix "$baseline_key"', script)
            self.assertIn('list-object-versions --no-paginate --bucket "$bucket" --prefix "$final_key"', script)
            self.assertIn('phase=publication-upload\n      aws s3api put-object', script)
            for code, stage in ((10, 'source-read'), (11, 's3-create'), (12, 's3-part'),
                                (13, 's3-complete'), (14, 'digest')):
                self.assertIn(f'{code}) phase=publication-{stage} ;;', script)
            self.assertIn('phase=publication-version\n    version=', script)
            self.assertIn('private cluster and archive diagnostics withheld', workflow)
            shell = '''set -euo pipefail
source <(sed -n '/^on_exit() {/,/^}/p' "$1")
work="$2/work"
mkdir "$work"
phase=publication
stage=publish-inventory
trap on_exit EXIT
false
'''
            result = subprocess.run(['bash', '-c', shell, 'bash', str(SCRIPT), directory],
                                    cwd=ROOT,
                                    env={**os.environ, 'OPENCLAW_PHASE_FILE': str(phase)},
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(phase.read_text(), 'publication\n')
            self.assertFalse((Path(directory) / 'work').exists())
            phase.unlink()
            result = subprocess.run(['bash', str(SCRIPT), 'archive'], cwd=ROOT,
                                    env={**os.environ, 'OPENCLAW_PHASE_FILE': str(phase)},
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(phase.read_text(), 'preflight\n')

    def test_s3_lookup_reports_only_fixed_error_category(self):
        shell = '''set -euo pipefail
source <(sed -n '/^lookup_baseline_versions() {/,/^}/p' "$1")
work="$2"
bucket=example
baseline_key=baseline.json
phase=publication-lookup
aws() {
  [[ " $* " == *' --no-paginate '* ]] || { printf 'missing unpaginated response\\n' >&2; return 1; }
  if [[ "$LOOKUP_ERROR" == truncated ]]; then printf '{"IsTruncated":true}\\n'; return 0; fi
  printf '%s\\n' "$LOOKUP_ERROR" >&2
  return 1
}
if lookup_baseline_versions; then exit 1; fi
printf '%s\\n' "$phase"
'''
        with tempfile.TemporaryDirectory() as directory:
            for error, expected in (('An error occurred (AccessDenied)',
                                     'publication-lookup-denied'),
                                    ('transport failed', 'publication-lookup-failed'),
                                    ('truncated', 'publication-lookup-response')):
                result = subprocess.run(['bash', '-c', shell, 'bash', str(SCRIPT), directory],
                                        cwd=ROOT, env={**os.environ, 'LOOKUP_ERROR': error},
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.strip(), expected)
                self.assertEqual(result.stderr, '')

    def test_private_workflow_runs_only_fixed_stages_from_current_main(self):
        workflow = WORKFLOW.read_text()
        for required in (
            'options: [none, inventory, publish-inventory, archive, publish-archive, verify]',
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
        self.assertIn('nohup sh /etc/openclaw-retirement/inventory-worker.sh', script)
        self.assertNotIn('"$worker" <scripts/ci/', script)
        self.assertEqual(script.count('run_inventory_worker'), 3)
        self.assertIn('observed="/private/legacy/baseline-${archive_id}.json"', script)
        self.assertIn('nohup flock -n /private/legacy/archive.lock', script)
        self.assertIn('archive_id="${ARCHIVE_REF##*/}"', script)
        self.assertIn('prefix="openclaw-enterprise/legacy/${GITHUB_SHA}/${GITHUB_RUN_ID}"', script)
        self.assertIn('python3 -I scripts/ci/openclaw-enterprise-upload.py', script)
        self.assertIn('(.publicationSha + "/" + .publicationRunId) == $ref', script)
        self.assertNotIn('--expected-size 80000000000', script)
        self.assertIn('validate_baseline "$work/observed.json" "$work/status.json"', script)
        self.assertIn('verify_restored_archive "$restore/receipt.json"', script)
        self.assertNotIn('"${reader[@]}" python3 /etc/openclaw-retirement/retirement.py inventory', script)
        self.assertIn('inventory-worker.sh=retirement/inventory-worker.sh',
                      (ROOT / 'clusters/homelab/apps/openclaw/kustomization.yaml').read_text())
        self.assertIn('mkdir "$directory/inventory.lock"', script)
        self.assertIn('/diagnostic.log" >/dev/null', script)
        self.assertIn("--body \"$work/baseline.json\" --if-none-match '*'", script)
        self.assertIn('[[ "$BASELINE_REF" == \'d55e2ab8521e427c059e07e34b270e476092a8a1/39127113354\' ]] || exit 1', script)
        self.assertIn('cmp "$work/baseline.json" "$work/offsite-baseline.json"', script)
        self.assertIn('refresh_status inventory', script)

    def test_detached_verify_worker_records_completion(self):
        source = SCRIPT.read_text()
        helper = 'verify_restored_archive() {' + source.split('verify_restored_archive() {', 1)[1].split('\n}\n\ncase "$stage" in', 1)[0] + '\n}'
        command = ('python3 /etc/openclaw-retirement/retirement.py verify-archive \\\n'
                   '        --config /private/legacy/config.json --receipt "$1"')
        for operation, expected in (('true', 'success'), ('false', 'failure')):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                marker = Path(directory) / 'verify-123.state'
                local = helper.replace('/private/legacy/verify-${GITHUB_RUN_ID}.state', str(marker))
                local = local.replace(command, operation).replace('sleep 30', 'sleep 0.1')
                shell = 'set -euo pipefail\nGITHUB_RUN_ID=123\nreader=()\n' + local + '\nverify_restored_archive /unused/receipt.json\n'
                result = subprocess.run(['bash', '-c', shell], cwd=ROOT, capture_output=True,
                                        text=True, timeout=5, check=False)
                self.assertEqual(result.returncode, 0 if operation == 'true' else 1,
                                 result.stderr)
                self.assertEqual(marker.read_text().strip(), expected)

    def test_publish_recovery_refuses_changed_baseline_identity(self):
        contract = json.loads((ROOT / 'scripts/config/openclaw-enterprise.json').read_text())[
            'legacyRetention']
        claims = {name: contract[name] for name in ('localClaim', 'stateClaim',
                                                    'agentClaim', 'nasClaim')}
        roots = {'local': {'device': 1, 'inode': 2, 'uid': contract['localUid']},
                 'nas': {'device': 3, 'inode': 4, 'uid': contract['nasUid']}}
        status = {'claims': claims, 'roots': roots, 'image': contract['image'],
                  'assistantSha256': contract['assistantSha256'], 'volumes': {
                      claim: {'pvcUid': 'pvc-uid', 'pvName': claim, 'pvUid': 'pv-uid'}
                      for claim in claims.values()}}
        tree = {'entries': 1, 'bytes': 1, 'sha256': 'a' * 64}
        baseline = {'format': 1, 'node': contract['node'], 'claims': claims,
                    'roots': {name: {**item, 'tree': tree} for name, item in roots.items()},
                    'rootIdentity': roots, 'kubernetes': {
                        'image': status['image'], 'assistantSha256': status['assistantSha256'],
                        'volumes': status['volumes']},
                    'requiredNas': contract['requiredNas'],
                    'databases': {name: {'bytes': 1, 'sha256': 'b' * 64}
                                  for name in contract['requiredLocal']}}
        shell = '''set -euo pipefail
source <(sed -n '/^validate_baseline() {/,/^}/p' "$1")
validate_baseline "$2" "$3"
'''
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            baseline_path, status_path = private / 'baseline.json', private / 'status.json'
            status_path.write_text(json.dumps(status))
            for changed, succeeds in (({}, True), ({'node': 'foreign-node'}, False),
                                      ({'rootIdentity': {}}, False),
                                      ({'databases': {}}, False),
                                      ({'databases': {name: {'bytes': '1', 'sha256': 'b' * 64}
                                                      for name in contract['requiredLocal']}}, False)):
                baseline_path.write_text(json.dumps({**baseline, **changed}))
                result = subprocess.run(['bash', '-c', shell, 'bash', str(SCRIPT),
                                         str(baseline_path), str(status_path)], cwd=ROOT,
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode == 0, succeeds)


if __name__ == '__main__':
    unittest.main()
