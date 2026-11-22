#!/usr/bin/env python3
"""Verify Deluge credential validation, scope, and secret containment offline."""

import base64
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'deluge-vpn-credentials.py'
SPEC = importlib.util.spec_from_file_location('deluge_credentials', SOURCE)
CREDENTIALS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CREDENTIALS)


def fixture_key(value):
    return base64.b64encode(bytes([value] * 32)).decode()


AIRVPN_PROFILE = f'''[Interface]
Address = 10.42.2.1/32, fd00::1/128
PrivateKey = {fixture_key(1)}
[Peer]
PublicKey = {fixture_key(2)}
PresharedKey = {fixture_key(3)}
Endpoint = 8.8.4.4:1637
'''
CLIENT = {'private': fixture_key(4), 'peer_public': fixture_key(5)}
GATEWAY = {'private': fixture_key(6), 'peer_public': fixture_key(7)}
BUNDLE = {'airvpn_profile': AIRVPN_PROFILE, 'client_transit': CLIENT, 'gateway_transit': GATEWAY}


def pubkey(args, *, input):
    if args != ['wg', 'pubkey']:
        raise AssertionError('Unexpected credential command')
    return {CLIENT['private']: GATEWAY['peer_public'], GATEWAY['private']: CLIENT['peer_public']}[input.strip()]


class CredentialsTest(unittest.TestCase):
    def test_bundle_and_transit_public_key_verification(self):
        with patch.object(CREDENTIALS, 'command', side_effect=pubkey) as command:
            profile, gateway, client = CREDENTIALS.validate_bundle(json.dumps(BUNDLE))
        self.assertEqual((profile, json.loads(gateway), json.loads(client)), (AIRVPN_PROFILE, GATEWAY, CLIENT))
        self.assertEqual(command.call_count, 2)
        mismatch = dict(BUNDLE, gateway_transit=dict(GATEWAY, peer_public=fixture_key(8)))
        with patch.object(CREDENTIALS, 'command', side_effect=pubkey), self.assertRaises(ValueError):
            CREDENTIALS.validate_bundle(json.dumps(mismatch))

    def test_bad_profile_and_duplicate_fields_fail_before_commands(self):
        invalid = dict(BUNDLE, airvpn_profile=AIRVPN_PROFILE.replace('8.8.4.4', 'airvpn.example.com'))
        invalid_values = ('{}', json.dumps(invalid), '{"airvpn_profile":"a","airvpn_profile":"b"}')
        with patch.object(CREDENTIALS, 'command') as command:
            for raw in invalid_values:
                with self.subTest(raw_length=len(raw)), self.assertRaises((ValueError, RuntimeError)):
                    CREDENTIALS.validate_bundle(raw)
        command.assert_not_called()

    def test_each_path_has_three_fixed_slots_checked_before_any_write(self):
        for path in ('a', 'b'):
            events = []
            targets = [f'/homelab/deluge/vpn/{path}/{slot}' for slot in CREDENTIALS.SLOTS]
            with (patch.object(sys, 'argv', ['credential', path]),
                  patch.dict(os.environ, {CREDENTIALS.BUNDLE_ENV: json.dumps(BUNDLE)}),
                  patch.object(CREDENTIALS, 'validate_context', side_effect=lambda: events.append('check')),
                  patch.object(CREDENTIALS, 'command', side_effect=pubkey),
                  patch.object(CREDENTIALS, 'require_parameter', side_effect=events.append),
                  patch.object(CREDENTIALS, 'store', side_effect=lambda name, _value: events.append(name) or 4),
                  redirect_stdout(io.StringIO()) as output):
                CREDENTIALS.rotate()
                self.assertNotIn(CREDENTIALS.BUNDLE_ENV, os.environ)
            self.assertEqual(events, ['check', *targets, 'check', *targets])
            self.assertIn('client-transit version 4', output.getvalue())
            self.assertNotIn(CLIENT['private'], output.getvalue())

    def test_wrong_metadata_prevents_all_writes(self):
        with (patch.object(sys, 'argv', ['credential', 'a']),
              patch.dict(os.environ, {CREDENTIALS.BUNDLE_ENV: json.dumps(BUNDLE)}),
              patch.object(CREDENTIALS, 'validate_context'),
              patch.object(CREDENTIALS, 'validate_bundle', return_value=('one', 'two', 'three')),
              patch.object(CREDENTIALS, 'command', return_value='{"Parameters":[]}'),
              patch.object(CREDENTIALS, 'store') as store,
              redirect_stderr(io.StringIO()) as output):
            self.assertEqual(CREDENTIALS.main(), 1)
        store.assert_not_called()
        self.assertIn('Private details withheld', output.getvalue())

    def test_store_uses_private_file_and_removes_it(self):
        paths = []

        def check(args):
            path = Path(args[args.index('--cli-input-json') + 1].removeprefix('file://'))
            paths.append(path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertNotIn(CLIENT['private'], str(args))
            self.assertEqual(json.loads(path.read_text()), {
                'Name': '/homelab/deluge/vpn/a/client-transit', 'Value': CLIENT['private'],
                'Type': 'SecureString', 'KeyId': 'alias/aws/ssm', 'Overwrite': True,
            })
            return '{"Version":9}'

        with patch.object(CREDENTIALS, 'command', side_effect=check):
            self.assertEqual(CREDENTIALS.store('/homelab/deluge/vpn/a/client-transit', CLIENT['private']), 9)
        self.assertFalse(paths[0].exists())

    def test_child_environment_and_error_output_contain_no_bundle(self):
        payload = json.dumps(BUNDLE)
        with (patch.dict(os.environ, {CREDENTIALS.BUNDLE_ENV: payload, 'AWS_ENDPOINT_URL': 'http://invalid'}),
              patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, payload, payload)) as run,
              self.assertRaises(RuntimeError) as error):
            CREDENTIALS.command(['aws', 'ssm', 'put-parameter'])
        self.assertNotIn(CLIENT['private'], str(error.exception))
        self.assertNotIn(CREDENTIALS.BUNDLE_ENV, run.call_args.kwargs['env'])
        self.assertNotIn('AWS_ENDPOINT_URL', run.call_args.kwargs['env'])
        self.assertEqual(run.call_args.kwargs['env']['AWS_IGNORE_CONFIGURED_ENDPOINT_URLS'], 'true')

    def test_requires_protected_dispatch_and_exact_head(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(CREDENTIALS, 'command') as command:
            with self.assertRaises(RuntimeError):
                CREDENTIALS.validate_context()
            command.assert_not_called()
        target = 'a' * 40
        context = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': CREDENTIALS.REPOSITORY,
                   'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                   'GITHUB_SHA': target, 'EXPECTED_SHA': target}
        with patch.dict(os.environ, context), patch.object(CREDENTIALS, 'command', side_effect=[target, 'b' * 40]):
            with self.assertRaises(RuntimeError):
                CREDENTIALS.validate_context()


if __name__ == '__main__':
    unittest.main()
