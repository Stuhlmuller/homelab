#!/usr/bin/env python3
"""Final acceptance report is a read-only, aggregate-only cleanup gate."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'clusters/homelab/apps/renovate'


class FinalReport(unittest.TestCase):
    def test_job_is_inert_and_cannot_write_or_reach_network(self):
        text = (APP / 'acceptance-final-report-job.yaml').read_text()
        policy = (APP / 'acceptance-final-report-networkpolicy.yaml').read_text()
        kustomization = (APP / 'kustomization.yaml').read_text()
        self.assertNotIn('acceptance-final-report-job.yaml', kustomization)
        self.assertIn('acceptance-final-report-networkpolicy.yaml', kustomization)
        self.assertEqual(len(re.findall(r'(?m)^kind: Job$', text)), 1)
        self.assertEqual(len(re.findall(r'(?m)^kind: NetworkPolicy$', policy)), 1)
        self.assertNotIn('kind: NetworkPolicy', text)
        for required in ('suspend: true', 'args: [report]',
                         'automountServiceAccountToken: false',
                         'readOnlyRootFilesystem: true',
                         'runAsUser: 12021', 'claimName: renovate-acceptance-ledger'):
            self.assertIn(required, text)
        for required in ('app.kubernetes.io/component: acceptance-final-report',
                         'policyTypes: [Ingress, Egress]', 'ingress: []', 'egress: []'):
            self.assertIn(required, policy)
        self.assertEqual(text.count('readOnly: true'), 3)
        self.assertNotIn('secretName:', text)
        self.assertNotIn('renovate-cache', text)
        self.assertNotIn('hostAliases:', text)
        self.assertNotIn('serviceAccountName: renovate-acceptance-schedule-collector', text)

    def test_report_directory_check_never_calls_mkdir(self):
        source = '''
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const observer = require(process.argv[1]);
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-final-report-'));
const make = fs.mkdirSync;
try {
  fs.mkdirSync = () => { throw new Error('write-attempt'); };
  assert.doesNotThrow(() => observer.privateDirectory(false, root));
  assert.throws(() => observer.privateDirectory(false, path.join(root, 'absent')), /ENOENT/);
  assert.throws(() => observer.privateDirectory(true, root), /write-attempt/);
} finally {
  fs.mkdirSync = make;
  fs.rmSync(root, { recursive: true, force: true });
}
'''
        result = subprocess.run(
            ['node', '-e', source, str(APP / 'acceptance-observer.js')],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
