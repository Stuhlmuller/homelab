#!/usr/bin/env python3
"""Fail-closed local checks for the protected legacy archive lane."""

import os
import subprocess
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/ci/openclaw-enterprise-operations.sh'
WORKFLOW = ROOT / '.github/workflows/openclaw-enterprise-operations.yml'


class Operations(unittest.TestCase):
    def test_versioned_restore_streams_exact_bytes(self):
        payload = b'archive\x00bytes'

        class S3(BaseHTTPRequestHandler):
            def do_GET(self):
                self.server.paths.append(self.path)
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        with HTTPServer(('127.0.0.1', 0), S3) as server, tempfile.TemporaryDirectory() as directory:
            server.paths = []
            Thread(target=server.serve_forever, daemon=True).start()
            destination = Path(directory) / 'archive'
            shell = '''set -euo pipefail
bucket=test
reader_input=()
aws() { command aws --endpoint-url "$TEST_ENDPOINT" --no-sign-request "$@"; }
source <(sed -n '/^restore_version() {/,/^}/p' "$1")
restore_version key version-1 "$2"
'''
            try:
                result = subprocess.run(['bash', '-c', shell, 'bash', str(SCRIPT), str(destination)],
                                        cwd=ROOT, env={**os.environ, 'TEST_ENDPOINT':
                                                       f'http://127.0.0.1:{server.server_port}'},
                                        capture_output=True, timeout=20, check=False)
            finally:
                server.shutdown()
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(parse_qs(urlsplit(server.paths[0]).query),
                             {'versionId': ['version-1']})

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


if __name__ == '__main__':
    unittest.main()
