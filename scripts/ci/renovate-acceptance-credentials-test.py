#!/usr/bin/env python3
"""Check the read-only App boundary and fixed SSM credential intake."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('credentials', ROOT / 'scripts' / 'renovate-acceptance-credentials.py')
credentials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(credentials)


class AcceptanceCredentials(unittest.TestCase):
    def test_both_app_and_owner_installation_must_be_read_only(self):
        permissions = {name: 'read' for name in credentials.READ_PERMISSIONS}
        registration = {'id': 42, 'client_id': 'Iv1.fixture', 'slug': 'read-only-fixture',
                        'permissions': permissions}
        installation = {'app_id': 42, 'account': {'login': 'Stuhlmuller'},
                        'repository_selection': 'all', 'permissions': permissions}
        responses = {'/app': registration, '/orgs/Stuhlmuller/installation': installation}
        with patch.object(credentials.github, 'app_jwt', return_value='fixture'), \
             patch.object(credentials.github, 'github_client',
                          return_value=lambda _method, route: responses[route]):
            credentials.validate_app('Iv1.fixture', 'private-key-fixture')
            for changed in ({'slug': 'rstuhlmuller-renovate'},
                            {'permissions': {**permissions, 'contents': 'write'}},
                            {'client_id': 'different'}):
                with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                    self._check_changed(responses, '/app', changed)
            for changed in ({'repository_selection': 'selected'},
                            {'permissions': {**permissions, 'checks': 'write'}},
                            {'app_id': 43}):
                with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                    self._check_changed(responses, '/orgs/Stuhlmuller/installation', changed)

    @staticmethod
    def _check_changed(responses, route, changed):
        previous = responses[route]
        responses[route] = {**previous, **changed}
        try:
            credentials.validate_app('Iv1.fixture', 'private-key-fixture')
        finally:
            responses[route] = previous

    def test_intake_checks_both_slots_before_exact_writes_without_secret_output(self):
        issuer = 'Iv1.fixture'
        key = '-----BEGIN RSA PRIVATE KEY-----\nfixture\n-----END RSA PRIVATE KEY-----'
        names = list(credentials.PARAMETERS.values())
        writes = []
        events = []

        def command(*args, env):
            self.assertNotIn(issuer, args)
            self.assertNotIn(key, args)
            self.assertNotIn('RENOVATE_ACCEPTANCE_APP_PRIVATE_KEY', env)
            self.assertNotIn('RENOVATE_ACCEPTANCE_APP_ISSUER_ID', env)
            if 'describe-parameters' in args:
                name = args[args.index('--parameter-filters') + 1].split('Values=')[1]
                events.append('metadata')
                return json.dumps({'Parameters': [{'Name': name, 'Type': 'SecureString',
                                                    'KeyId': 'alias/aws/ssm', 'Tier': 'Standard'}]}).encode()
            self.assertIn('put-parameter', args)
            path = Path(args[args.index('--cli-input-json') + 1].removeprefix('file://'))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            payload = json.loads(path.read_text())
            self.assertIn(payload['Name'], names)
            self.assertIn(payload['Value'], (issuer, key))
            writes.append(payload['Name'])
            events.append('write')
            return b'{"Version":2}'

        output = io.StringIO()
        with patch.dict(os.environ, {'RENOVATE_ACCEPTANCE_APP_ISSUER_ID': issuer,
                                     'RENOVATE_ACCEPTANCE_APP_PRIVATE_KEY': key}, clear=True), \
             patch.object(sys, 'argv', ['intake']), patch.object(credentials, 'context'), \
             patch.object(credentials, 'validate_app') as validate, \
             patch.object(credentials, 'command', side_effect=command), \
             contextlib.redirect_stdout(output):
            credentials.inject()
            validate.assert_called_once_with(issuer, key)
        self.assertEqual(writes, names)
        self.assertEqual(events, ['metadata', 'metadata', 'write', 'write'])
        self.assertNotIn(issuer, output.getvalue())
        self.assertNotIn(key, output.getvalue())

    def test_invalid_slot_fails_before_first_write(self):
        key = '-----BEGIN PRIVATE KEY-----\nfixture\n-----END PRIVATE KEY-----'
        calls = []

        def command(*args, env):
            calls.append(args)
            if 'put-parameter' in args:
                self.fail('invalid metadata must never write')
            name = args[args.index('--parameter-filters') + 1].split('Values=')[1]
            return json.dumps({'Parameters': [{'Name': name, 'Type': 'String',
                                                'KeyId': 'alias/aws/ssm', 'Tier': 'Standard'}]}).encode()

        with patch.dict(os.environ, {'RENOVATE_ACCEPTANCE_APP_ISSUER_ID': 'Iv1.fixture',
                                     'RENOVATE_ACCEPTANCE_APP_PRIVATE_KEY': key}, clear=True), \
             patch.object(sys, 'argv', ['intake']), patch.object(credentials, 'context'), \
             patch.object(credentials, 'validate_app'), \
             patch.object(credentials, 'command', side_effect=command):
            with self.assertRaises(RuntimeError):
                credentials.inject()
        self.assertEqual(len(calls), 1)

    def test_context_rejects_untrusted_event_before_git(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(credentials.github, 'verify_reviewed_main') as guard:
            with self.assertRaises(RuntimeError):
                credentials.context()
            guard.assert_not_called()

    def test_workflow_has_only_acceptance_ssm_write_targets(self):
        workflow = (ROOT / '.github/workflows/renovate-acceptance-credentials.yml').read_text()
        for name in credentials.PARAMETERS.values():
            self.assertIn(name.removeprefix('/'), workflow)
        self.assertNotIn('parameter/homelab/renovate/github-app/', workflow)
        self.assertIn('environment:\n      name: homelab-production', workflow)
        self.assertIn('run: python3 -I scripts/renovate-acceptance-credentials.py', workflow)


if __name__ == '__main__':
    unittest.main()
