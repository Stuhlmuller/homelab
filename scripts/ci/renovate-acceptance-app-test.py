#!/usr/bin/env python3
"""Failure cases for the dedicated Renovate acceptance App intake."""
import argparse
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('acceptance_app', ROOT / 'scripts' / 'renovate-acceptance-app.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

PEM_LABEL = 'PRIVATE KEY'
PEM_FIXTURE = f'-----BEGIN {PEM_LABEL}-----\nfixture\n-----END {PEM_LABEL}-----'


class AcceptanceAppTests(unittest.TestCase):
    def test_ephemeral_secret_is_owned_and_deleted_with_provider_or_externalsecret(self):
        source = (ROOT / 'clusters/homelab/apps/renovate/acceptance-externalsecret.yaml').read_text()
        self.assertIn('creationPolicy: Owner', source)
        self.assertIn('deletionPolicy: Delete', source)
        self.assertIn('name: renovate-acceptance', source)
        self.assertNotIn('name: renovate\n', source)
        for name in app.SSM.values():
            self.assertIn(f'key: {name}', source)

    def test_manifest_and_callback_cannot_expand_grants_or_skip_state(self):
        declared = app.manifest('http://127.0.0.1:4123/callback')
        self.assertEqual(declared['default_permissions'], {
            name: 'read' for name in ('administration', 'checks', 'contents', 'issues', 'members', 'metadata',
                                     'pull_requests', 'statuses', 'vulnerability_alerts')})
        self.assertEqual(declared['default_events'], [])
        self.assertFalse(declared['hook_attributes']['active'])
        self.assertFalse(declared['public'])
        code = 'a' * 40
        self.assertEqual(app.parse_callback(f'code={code}&state=good', 'good'), code)
        for query in (f'code={code}&state=wrong', f'code={code}',
                      f'code={code}&code={code}&state=good',
                      f'code={code}&state=good&extra=1'):
            with self.subTest(query=query), self.assertRaises(RuntimeError):
                app.parse_callback(query, 'good')

    def test_app_and_installation_need_exact_read_grants_and_all_repositories(self):
        grants = app.READ_PERMISSIONS.copy()
        registration = {'id': 42, 'name': app.APP_NAME,
                        'owner': {'login': 'Stuhlmuller', 'type': 'Organization'},
                        'permissions': grants, 'events': [], 'slug': 'fixture-observer'}
        installation = {'app_id': 42, 'account': {'login': 'Stuhlmuller'},
                        'repository_selection': 'all', 'permissions': grants}
        responses = {'/app': registration, '/orgs/Stuhlmuller/installation': installation}
        def api(_method, path):
            return responses[path]

        with patch.object(app.github, 'app_jwt', return_value='fixture'), \
             patch.object(app.github, 'github_client', return_value=api):
            returned, _ = app.validate_registration(42, PEM_FIXTURE)
            app.validate_installation(returned, 42)
            for key, changed in (("permissions", {**grants, 'contents': 'write'}),
                                 ('permissions', {**grants, 'administration': 'write'}),
                                 ('permissions', {key: value for key, value in grants.items()
                                                  if key != 'administration'}),
                                 ('events', ['push']), ('name', 'another app'),
                                 ('owner', {'login': 'other', 'type': 'Organization'})):
                with self.subTest(key=key, changed=changed):
                    responses['/app'] = {**registration, key: changed}
                    with self.assertRaises(RuntimeError):
                        app.validate_registration(42, PEM_FIXTURE)
            responses['/app'] = registration
            for changed in ({'repository_selection': 'selected'},
                            {'permissions': {**grants, 'issues': 'write'}}):
                with self.subTest(changed=changed):
                    responses['/orgs/Stuhlmuller/installation'] = {**installation, **changed}
                    with self.assertRaises(RuntimeError):
                        app.validate_installation(api, 42)

    def test_declared_placeholders_required_and_pem_uses_only_stdin(self):
        names = list(app.SSM.values())
        metadata = {'Parameters': [{'Name': name, 'Type': 'SecureString',
                                    'Tier': 'Standard', 'KeyId': 'alias/aws/ssm'} for name in names]}
        values = {'Parameters': [{'Name': name, 'Value': 'REPLACE_ME', 'Version': 1}
                                 for name in names], 'InvalidParameters': []}

        def fake_aws(_profile, *args, payload=None):
            if 'describe-parameters' in args:
                return json.dumps(metadata).encode()
            if 'get-parameters' in args:
                return json.dumps(values).encode()
            raise AssertionError('Preflight must not write to SSM')

        with patch.object(app, 'aws_command', side_effect=fake_aws):
            app.ssm_slots('fixture', require_placeholder=True)
            values['Parameters'][0]['Value'] = 'existing-secret'
            with self.assertRaises(RuntimeError):
                app.ssm_slots('fixture', require_placeholder=True)

        secret = PEM_FIXTURE
        calls = []

        def fake_subprocess(arguments, **kwargs):
            calls.append((arguments, kwargs))
            self.assertNotIn(secret, arguments)
            self.assertNotIn(secret, str(kwargs['env']))
            self.assertNotIn('AWS_ACCESS_KEY_ID', kwargs['env'])
            self.assertIn(('--value', 'file:///dev/stdin'), tuple(zip(arguments, arguments[1:])))
            self.assertEqual(kwargs['input'], secret.encode())
            return subprocess.CompletedProcess(arguments, 0, b'{"Version":2}', b'')

        with patch.dict(app.os.environ, {'AWS_ACCESS_KEY_ID': 'fixture'}, clear=True), \
             patch.object(app.subprocess, 'run', side_effect=fake_subprocess):
            app.put_parameter('fixture', app.SSM['private-key'], secret)
        self.assertEqual(len(calls), 1)

    def test_partial_transfer_resumes_only_exact_read_only_app_and_issuer_slot(self):
        secret = PEM_FIXTURE
        key = {'Name': app.SSM['private-key'], 'Value': secret, 'Version': 2}
        issuer = {'Name': app.SSM['issuer-id'], 'Value': app.PLACEHOLDER, 'Version': 1}
        slots = {app.SSM['private-key']: key, app.SSM['issuer-id']: issuer}
        args = argparse.Namespace(action='resume', profile='fixture', expected_sha='a' * 40,
                                  app_id=42)
        output = io.StringIO()
        with patch.object(app.github, 'verify_reviewed_main') as reviewed, \
             patch.object(app, 'sso_preflight'), \
             patch.object(app, 'ssm_slots', return_value=slots) as read_slots, \
             patch.object(app, 'validate_registration', return_value=(None, 'fixture-observer')) as validate, \
             patch.object(app, 'put_parameter') as write, redirect_stdout(output):
            app.run(args)
        self.assertEqual(reviewed.call_count, 2)
        self.assertEqual(read_slots.call_count, 2)
        validate.assert_called_once_with(42, secret)
        write.assert_called_once_with('fixture', app.SSM['issuer-id'], '42')
        self.assertNotIn(secret, output.getvalue())

        # A lost CLI receipt after the issuer write is safe to retry without
        # incrementing either parameter version again.
        issuer['Value'], issuer['Version'] = '42', 2
        with patch.object(app.github, 'verify_reviewed_main') as reviewed, \
             patch.object(app, 'sso_preflight'), \
             patch.object(app, 'ssm_slots', return_value=slots), \
             patch.object(app, 'validate_registration', return_value=(None, 'fixture-observer')), \
             patch.object(app, 'put_parameter') as write, redirect_stdout(io.StringIO()):
            app.run(args)
        reviewed.assert_called_once()
        write.assert_not_called()

    def test_create_prints_public_recovery_id_before_partial_write_failure(self):
        secret = PEM_FIXTURE
        args = argparse.Namespace(action='create', profile='fixture', expected_sha='a' * 40,
                                  app_id=None)
        output = io.StringIO()
        with patch.object(app.github, 'verify_reviewed_main'), \
             patch.object(app, 'sso_preflight'), \
             patch.object(app, 'ssm_slots'), \
             patch.object(app, 'callback_code', return_value='fixture-code'), \
             patch.object(app, 'exchange', return_value={'id': 42, 'pem': secret}), \
             patch.object(app, 'validate_registration', return_value=(None, 'fixture-observer')), \
             patch.object(app, 'put_parameter', side_effect=[None, RuntimeError('issuer failure')]) as write, \
             redirect_stdout(output):
            with self.assertRaises(RuntimeError):
                app.run(args)
        self.assertEqual(write.call_args_list[0].args,
                         ('fixture', app.SSM['private-key'], secret))
        self.assertEqual(write.call_args_list[1].args,
                         ('fixture', app.SSM['issuer-id'], '42'))
        self.assertIn('Validated acceptance App ID 42 (fixture-observer)', output.getvalue())
        self.assertNotIn(secret, output.getvalue())

    def test_resume_rejects_incomplete_mismatched_or_changed_slots(self):
        secret = PEM_FIXTURE
        key = {'Name': app.SSM['private-key'], 'Value': secret, 'Version': 2}
        issuer = {'Name': app.SSM['issuer-id'], 'Value': app.PLACEHOLDER, 'Version': 1}
        slots = {app.SSM['private-key']: key, app.SSM['issuer-id']: issuer}
        with patch.object(app.github, 'verify_reviewed_main'), \
             patch.object(app, 'ssm_slots', return_value=slots), \
             patch.object(app, 'validate_registration', return_value=(None, 'fixture-observer')), \
             patch.object(app, 'put_parameter') as write:
            for key_version, issuer_version, issuer_value in (
                    (1, 1, app.PLACEHOLDER), (3, 1, app.PLACEHOLDER),
                    (2, 2, '99'), (2, 3, '42')):
                with self.subTest(key_version=key_version, issuer_version=issuer_version):
                    key['Version'] = key_version
                    issuer['Version'], issuer['Value'] = issuer_version, issuer_value
                    with self.assertRaises(RuntimeError):
                        app.resume_transfer('fixture', 'a' * 40, 42, slots)
            write.assert_not_called()

            key['Version'] = 2
            issuer['Version'], issuer['Value'] = 1, app.PLACEHOLDER
            with patch.object(app, 'validate_registration', side_effect=RuntimeError('wrong App')):
                with self.assertRaises(RuntimeError):
                    app.resume_transfer('fixture', 'a' * 40, 42, slots)
            write.assert_not_called()

        changed = {**slots, app.SSM['issuer-id']: {**issuer, 'Value': '99', 'Version': 2}}
        with patch.object(app.github, 'verify_reviewed_main'), \
             patch.object(app, 'ssm_slots', return_value=changed), \
             patch.object(app, 'validate_registration', return_value=(None, 'fixture-observer')), \
             patch.object(app, 'put_parameter') as write:
            with self.assertRaises(RuntimeError):
                app.resume_transfer('fixture', 'a' * 40, 42, slots)
            write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
