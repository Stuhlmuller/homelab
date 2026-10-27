#!/usr/bin/env python3
"""Keep every staged acceptance workload off the Renovate writer Secret."""
from pathlib import Path
import re
import unittest

APP = Path(__file__).resolve().parents[2] / 'clusters/homelab/apps/renovate'
CREDENTIALED = {
    'acceptance-observer-cronjob.yaml', 'acceptance-inventory-job.yaml',
    'acceptance-pr-proof-job.yaml', 'acceptance-pr-proof-cronjob.yaml',
}


class AcceptanceSecretBoundary(unittest.TestCase):
    def test_jobs_use_only_dedicated_read_only_app_secret(self):
        workloads = []
        for path in sorted(APP.glob('acceptance-*.yaml')):
            if path.name not in CREDENTIALED:
                continue
            content = path.read_text()
            self.assertRegex(content, r'(?m)^kind: (?:CronJob|Job)$')
            workloads.append(path.name)
            with self.subTest(path=path.name):
                self.assertEqual(len(re.findall(r'(?m)^\s+secretName: renovate-acceptance$',
                                                content)), 1)
                self.assertEqual(content.count('mountPath: /var/run/secrets/renovate-acceptance'), 1)
                self.assertNotRegex(content, r'(?m)^\s+secretName: renovate\s*$')
                self.assertIn('automountServiceAccountToken: false', content)
                if path.name == 'acceptance-inventory-job.yaml':
                    self.assertRegex(content,
                                     r'(?m)^\s+secretName: renovate-acceptance-review$')
                    self.assertEqual(content.count('mountPath: /review'), 1)
                else:
                    self.assertNotIn('renovate-acceptance-review', content)
        self.assertGreaterEqual(len(workloads), 4)

    def test_outcome_jobs_have_only_the_private_review_secret(self):
        for name in ('acceptance-outcome-amend-job.yaml',
                     'acceptance-outcome-preflight-job.yaml'):
            with self.subTest(name=name):
                manifest = (APP / name).read_text()
                self.assertIn('secretName: renovate-acceptance-outcome-review', manifest)
                self.assertEqual(manifest.count('mountPath: /review'), 1)
                self.assertNotRegex(manifest, r'(?m)^\s+secretName: renovate(?:-acceptance)?\s*$')
                self.assertNotIn('mountPath: /var/run/secrets/renovate', manifest)
                self.assertNotIn('claimName: renovate-cache', manifest)
                self.assertIn('automountServiceAccountToken: false', manifest)


if __name__ == '__main__':
    unittest.main()
