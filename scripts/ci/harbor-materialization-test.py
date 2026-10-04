#!/usr/bin/env python3
"""Offline candidate composition/trust boundaries and metadata regressions."""
import argparse
import importlib.util
import json
import ssl
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / 'clusters/homelab/apps/harbor-tls-candidate'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


tls = module('tls', ROOT / 'scripts/harbor-tls-render.py')
life = module('life', CANDIDATE / 'lifecycle-metrics.py')
bootstrap = module('candidate_bootstrap', CANDIDATE / 'bootstrap.py')


class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rendered = tls.render(ARGS.chart, ARGS.helm)
        cls.overlay = list(yaml.safe_load_all(subprocess.check_output([ARGS.kustomize, 'build', str(CANDIDATE)])))

    def test_public_materialization_matches_render_without_secrets(self):
        expected = tls.public_overrides(self.rendered)
        stored = list(yaml.safe_load_all((CANDIDATE / 'nginx-public.yaml').read_text()))
        self.assertEqual(stored, expected)
        self.assertNotIn('Secret', {r['kind'] for r in stored})
        self.assertEqual(list(yaml.safe_load_all((CANDIDATE / 'certificates.yaml').read_text())), tls.supporting()[2:])

    def test_last_source_wins_exactly_three_chart_objects(self):
        def key(r):
            return r['kind'], r['metadata'].get('namespace', 'harbor'), r['metadata']['name']
        chart = {key(r): r for r in self.rendered if r['kind'] not in ('DestinationRule', 'VirtualService', 'Issuer', 'Certificate')}
        repeated = set(chart) & {key(r) for r in self.overlay}
        self.assertEqual(repeated, {('ConfigMap', 'harbor', 'harbor-nginx'),
                                    ('Deployment', 'harbor', 'harbor-nginx'), ('Service', 'harbor', 'harbor')})
        chart.update({key(r): r for r in self.overlay})
        tls.check(list(chart.values()))

    def test_hooks_skipped_schedule_suspended_exporter_stopped(self):
        for name in ('harbor-bootstrap', 'harbor-postgres-backup-initial'):
            self.assertEqual(tls.one(self.overlay, 'Job', name)['metadata']['annotations']['argocd.argoproj.io/hook'], 'Skip')
        self.assertIs(tls.one(self.overlay, 'CronJob', 'harbor-postgres-backup')['spec']['suspend'], True)
        self.assertEqual(tls.one(self.overlay, 'Deployment', 'harbor-vulnerability-exporter')['spec']['replicas'], 0)

    def test_metadata_container_has_no_credential_or_token_mount(self):
        pod = tls.one(self.overlay, 'Deployment', 'harbor-vulnerability-exporter')['spec']['template']['spec']
        sidecar = next(c for c in pod['containers'] if c['name'] == 'lifecycle-metrics')
        self.assertEqual({v['name'] for v in sidecar['volumeMounts']}, {'lifecycle-metadata', 'lifecycle-script'})
        volume = next(v for v in pod['volumes'] if v['name'] == 'lifecycle-metadata')
        self.assertEqual(volume['secret']['items'], [{'key': 'expires-at', 'path': 'expires-at'}])
        self.assertIs(pod['automountServiceAccountToken'], False)
        ports = tls.one(self.overlay, 'Service', 'harbor-vulnerability-exporter')['spec']['ports']
        self.assertEqual({p['port'] for p in ports}, {8080, 8081})

    def test_migrated_backend_ports_match_chart(self):
        policy = tls.one(self.overlay, 'NetworkPolicy', 'harbor-components')
        self.assertEqual({p['port'] for p in policy['spec']['ingress'][0]['ports']}, {8443, 5443, 6379})
        for name in ('harbor-core', 'harbor-jobservice', 'harbor-portal', 'harbor-trivy', 'harbor-registry'):
            ports = tls.one(self.rendered, 'Service', name)['spec']['ports']
            self.assertTrue({p.get('targetPort', p['port']) for p in ports} <= {8443, 5443, 8001})

    def test_trust_generators_are_public_only_and_input_absent(self):
        trust = yaml.safe_load((CANDIDATE / 'trust/kustomization.yaml').read_text())
        self.assertEqual(len(trust['configMapGenerator']), 1)
        self.assertEqual(len(trust['secretGenerator']), 2)
        for generator in trust['configMapGenerator'] + trust['secretGenerator']:
            self.assertEqual(generator['files'], ['ca.crt=inputs/ca.crt'])
        self.assertFalse((CANDIDATE / 'trust/inputs/ca.crt').exists())

    def test_tls_bootstrap_fixed_endpoint_roots_no_plaintext(self):
        with patch.object(bootstrap.ssl, 'create_default_context') as context:
            client = bootstrap.Client('SYNTHETIC')
            context.assert_called_once_with(cafile='/etc/harbor/backend-trust/ca.crt')
            self.assertEqual(context.return_value.minimum_version, ssl.TLSVersion.TLSv1_2)
            self.assertEqual(client.endpoint, 'https://harbor-core.harbor.svc.cluster.local')
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.Client('SYNTHETIC', endpoint='http://harbor-core')

    def test_reload_values_target_every_certificate_client(self):
        for path in (CANDIDATE / 'rotation').glob('*.values.yaml'):
            values = yaml.safe_load(path.read_text())
            self.assertEqual(set(values), {'nginx', 'core', 'portal', 'jobservice', 'registry', 'trivy', 'exporter'})
            self.assertTrue(all(v['podAnnotations'] for v in values.values()))

    def test_metrics_healthy_expired_and_invalid(self):
        now = 1800000000
        for value, valid in ((str(now + 86400), True), (str(now - 1), True),
                             ('secret-text', False), ('0', False), ('-1', False),
                             (str(now + 31 * 86400), False)):
            with patch.object(life, 'EXPIRY') as file:
                file.read_text.return_value = value
                result = life.metrics(now)
            self.assertIn(f'harbor_collector_expiry_metadata_valid {int(valid)}', result)
            self.assertEqual('expires_at_seconds' in result, valid)
            self.assertNotIn('secret-text', result)

    def test_missing_metadata_never_reports_healthy(self):
        with patch.object(life, 'EXPIRY') as file:
            file.read_text.side_effect = OSError('private-text')
            self.assertEqual(life.metrics(1800000000), 'harbor_collector_expiry_metadata_valid 0\n')

    def test_sources_are_unregistered_and_pause_is_declared(self):
        sources = yaml.safe_load((CANDIDATE / 'application-sources.patch.yaml').read_text())['spec']
        self.assertEqual(sources['sources'][-1]['path'], str(CANDIDATE.relative_to(ROOT)))
        self.assertIs(sources['syncPolicy']['automated']['enabled'], False)
        self.assertNotIn('harbor-tls-candidate', (ROOT / 'IaC/terragrunt.stack.hcl').read_text())
        self.assertFalse(json.loads((ROOT / 'scripts/config/harbor-vulnerability-lifecycle.json').read_text())['execution_enabled'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--chart', type=Path, required=True)
    parser.add_argument('--helm', default='helm')
    parser.add_argument('--kustomize', default='kustomize')
    ARGS, remaining = parser.parse_known_args()
    unittest.main(argv=['harbor-materialization-test'] + remaining)
