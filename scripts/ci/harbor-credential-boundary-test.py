#!/usr/bin/env python3
"""Regression checks for the proposed reader split, not an IAM evaluator."""
import copy
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PARAMETER = '/homelab/harbor/vulnerability-robot-password'
ARN = 'arn:aws:ssm:us-west-2:716182248480:parameter' + PARAMETER
CANDIDATE = ROOT / 'clusters/homelab/apps/harbor/credential-candidate'
spec = importlib.util.spec_from_file_location('boundary', ROOT / 'scripts/harbor-credential-boundary-inventory.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def reader_policy(policy):
    expected = [
        {'Sid': 'OneCollectorEnvelope', 'Effect': 'Allow', 'Action': ['ssm:GetParameter'], 'Resource': ARN},
        {'Sid': 'OneEnvelopeViaSsmOnly', 'Effect': 'Allow', 'Action': ['kms:Decrypt'],
         'Resource': 'arn:aws:kms:us-west-2:716182248480:key/*',
         'Condition': {'StringEquals': {'kms:ViaService': 'ssm.us-west-2.amazonaws.com',
                                      'kms:CallerAccount': '716182248480',
                                      'kms:EncryptionContext:PARAMETER_ARN': ARN},
                       'ForAnyValue:StringEquals': {'kms:ResourceAliases': 'alias/aws/ssm'}}}]
    if policy != {'Version': '2012-10-17', 'Statement': expected}:
        raise ValueError('Reader policy widened or changed; review required')


class BoundaryTests(unittest.TestCase):
    def policy(self):
        return json.loads((ROOT / 'scripts/config/harbor-vulnerability-reader-policy.json').read_text())

    def test_exact_reader_policy(self):
        reader_policy(self.policy())

    def test_reader_write_path_reads_and_other_parameters_rejected(self):
        for action in ('ssm:PutParameter', 'ssm:GetParametersByPath', 'ssm:*', 'ssm:GetParameterHistory'):
            value = self.policy()
            value['Statement'][0]['Action'].append(action)
            with self.assertRaises(ValueError):
                reader_policy(value)
        value = self.policy()
        value['Statement'][0]['Resource'] = '*'
        with self.assertRaises(ValueError):
            reader_policy(value)

    def test_missing_kms_context_rejected(self):
        value = self.policy()
        del value['Statement'][1]['Condition']['StringEquals']['kms:EncryptionContext:PARAMETER_ARN']
        with self.assertRaises(ValueError):
            reader_policy(value)

    def test_catalog_excludes_shared_reader_and_additional_list(self):
        text = (ROOT / 'IaC/.catalog/units/live/aws-ssm-parameters/terragrunt.hcl').read_text()
        block = re.search(r'^    "' + re.escape(PARAMETER) + r'" = \{\n(.*?)^    }', text, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(block)
        self.assertRegex(block[1], r'\breader_access\s*=\s*false\b')
        additional = re.search(r'additional_parameter_reader_names\s*=\s*\[(.*?)\]', text, re.DOTALL)
        self.assertIsNotNone(additional)
        self.assertNotIn(PARAMETER, additional[1])

    def test_namespace_scoped_store_with_separate_auth(self):
        es = yaml.safe_load((CANDIDATE / 'externalsecret.yaml').read_text())
        store = yaml.safe_load((CANDIDATE / 'secretstore.yaml').read_text())
        self.assertEqual(es['spec']['secretStoreRef'], {'kind': 'SecretStore', 'name': 'harbor-vulnerability-reader'})
        self.assertEqual(store['kind'], 'SecretStore')
        self.assertEqual(store['metadata']['namespace'], 'harbor')
        self.assertEqual(es['metadata']['namespace'], 'harbor')
        aws = store['spec']['provider']['aws']
        self.assertEqual(set(aws), {'service', 'region', 'auth'})
        self.assertEqual(aws['auth']['secretRef'], {
            'accessKeyIDSecretRef': {'name': 'harbor-vulnerability-reader-auth', 'key': 'access-key-id'},
            'secretAccessKeySecretRef': {'name': 'harbor-vulnerability-reader-auth', 'key': 'secret-access-key'}})
        self.assertEqual(es['spec']['data'][0]['remoteRef']['property'], 'secret')
        self.assertEqual(es['spec']['data'][0]['remoteRef']['key'], PARAMETER)

    def test_no_auth_secret_or_new_store_in_active_base(self):
        candidate = yaml.safe_load((CANDIDATE / 'kustomization.yaml').read_text())
        self.assertEqual(sorted(candidate['resources']), ['externalsecret.yaml', 'secretstore.yaml'])
        base = (CANDIDATE.parent / 'kustomization.yaml').read_text()
        self.assertNotIn('credential-candidate', base)
        self.assertNotIn('harbor-vulnerability-reader', base)

    def test_workflow_remains_hard_disabled_and_session_request_explicit(self):
        job = yaml.safe_load((ROOT / '.github/workflows/harbor-vulnerability-credential.yml').read_text())['jobs']['credential']
        self.assertIs(job['if'], False)
        self.assertEqual(job['timeout-minutes'], 10)
        steps = [s for s in job['steps'] if 'aws-actions/configure-aws-credentials@' in s.get('uses', '')]
        self.assertEqual(steps[0]['with']['role-duration-seconds'], 900)

    def test_inventory_emits_references_not_secret_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'clusters').mkdir()
            (root / '.github/workflows').mkdir(parents=True)
            items = [{'kind': 'Secret', 'metadata': {'name': 'fixture'}, 'stringData': {'secret': 'SYNTHETIC_PRIVATE'}},
                     {'kind': 'ExternalSecret', 'metadata': {'name': 'one', 'namespace': 'harbor'},
                      'spec': {'secretStoreRef': {'kind': 'SecretStore', 'name': 'local'},
                               'target': {'template': {'data': {'private': 'SYNTHETIC_PRIVATE'}}}}}]
            (root / 'clusters/fixtures.yaml').write_text(yaml.safe_dump_all(copy.deepcopy(items)))
            result = m.inventory(root)
            self.assertEqual(len(result['consumers']), 1)
            self.assertNotIn('SYNTHETIC_PRIVATE', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
