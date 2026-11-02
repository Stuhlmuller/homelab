#!/usr/bin/env python3
"""Reject partial, substituted, or unrelated zero-finding controller reports."""

from copy import deepcopy
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

SCAN = runpy.run_path(str(Path(__file__).with_name('scan.py')))
MODULES = {**SCAN['SOURCE']['modules'], 'k8s.io/client-go': {'version': 'v0.33.2'}}
PACKAGES = [{'Name': 'github.com/rancher/local-path-provisioner'},
            {'Name': 'stdlib', 'Version': 'v' + SCAN['SOURCE']['go_version']}]
PACKAGES.extend({'Name': k, 'Version': v['version']} for k, v in MODULES.items())
REPORT = {'SchemaVersion': 2, 'ArtifactType': 'container_image',
          'Metadata': {'ImageID': 'config', 'DiffIDs': ['layer']},
          'Results': [{'Type': 'gobinary', 'Target': SCAN['BINARY'], 'Packages': PACKAGES}]}


class CoverageTests(unittest.TestCase):
    def verify(self, report):
        return SCAN['covered_packages'](report, 'config', ['layer'], MODULES)

    def test_complete_scan_passes(self):
        self.assertEqual(self.verify(REPORT), len(MODULES) + 1)

    def test_partial_or_substituted_version_fails(self):
        for mutation in (lambda packages: packages.pop(),
                         lambda packages: packages[-1].update(Version='unreviewed'),
                         lambda packages: packages.append(dict(packages[-1]))):
            report = deepcopy(REPORT)
            mutation(report['Results'][0]['Packages'])
            with self.assertRaises(ValueError):
                self.verify(report)

    def test_wrong_artifact_target_or_findings_fail(self):
        for mutation in (lambda r: r.update(Results=[]), lambda r: r['Metadata'].update(ImageID='other'),
                         lambda r: r['Metadata'].update(DiffIDs=['other']),
                         lambda r: r['Results'][0].update(Target='unrelated'),
                         lambda r: r['Results'][0].update(Vulnerabilities=[{'Severity': 'HIGH'}])):
            report = deepcopy(REPORT)
            mutation(report)
            with self.assertRaises(ValueError):
                self.verify(report)

    def test_alternate_entrypoint_cannot_reuse_the_controller(self):
        config = SCAN['BUILD']['image_config']('amd64', 'sha256:' + 'a' * 64)

        def encode():
            return json.dumps(config, sort_keys=True, separators=(',', ':')).encode()

        SCAN['verify_config'](encode(), 'amd64', 'sha256:' + 'a' * 64)
        config['config']['Entrypoint'] = ['/controller-that-does-not-exist']
        with self.assertRaisesRegex(ValueError, 'runtime configuration'):
            SCAN['verify_config'](encode(), 'amd64', 'sha256:' + 'a' * 64)

    def test_trivy_uses_private_cwd_and_explicit_empty_configuration(self):
        with tempfile.TemporaryDirectory() as directory, patch('subprocess.run') as run:
            work = Path(directory)
            SCAN['run_trivy']('trivy', ['image', 'fixture'], work, {})
            argv = run.call_args.args[0]
            config = Path(argv[argv.index('--config') + 1])
            self.assertEqual(run.call_args.kwargs['cwd'], work)
            self.assertEqual(config.parent, work)
            self.assertEqual(json.loads(config.read_text()), {})


if __name__ == '__main__':
    unittest.main()
