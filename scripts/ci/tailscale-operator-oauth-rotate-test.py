#!/usr/bin/env python3
"""Offline checks for the operator OAuth one-shot boundary and retry path."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import tempfile
from unittest.mock import patch


source = Path(__file__).resolve().parents[1] / 'tailscale-operator-oauth-rotate.py'
spec = importlib.util.spec_from_file_location('rotation', source)
rotation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rotation)
admin_key = 'tskey-api-fixture-secret'
new_id = 'fixture-client-id'
new_secret = 'fixture-new-client-secret'
old = {'client_id': 'old-id', 'client_secret': 'old-secret'}


def private_fixture(directory, name, value):
    path = directory / name
    path.write_text(value)
    path.chmod(0o600)
    return path


with tempfile.TemporaryDirectory() as location:
    directory = Path(location)
    directory.chmod(0o700)
    key_file = private_fixture(directory, 'admin-key', admin_key + '\n')
    receipt = directory / 'receipt.json'
    assert rotation.read_api_key(key_file) == admin_key
    directory.chmod(0o755)
    try:
        rotation.read_api_key(key_file)
        raise AssertionError('Shared API key directory accepted')
    except RuntimeError:
        pass
    directory.chmod(0o700)
    key_file.chmod(0o644)
    try:
        rotation.read_api_key(key_file)
        raise AssertionError('Shared API key accepted')
    except RuntimeError:
        pass
    key_file.chmod(0o600)
    (directory / 'linked-key').symlink_to(key_file)
    try:
        rotation.read_api_key(directory / 'linked-key')
        raise AssertionError('Symlink API key accepted')
    except RuntimeError:
        pass

    read_state = {name: {'Name': parameter, 'Type': 'SecureString', 'Version': 2,
                         'Value': old[name]} for name, parameter in rotation.PARAMETERS.items()}
    with patch.object(rotation, 'current_main', return_value='a' * 40), \
            patch.object(rotation, 'validate_contract'), \
            patch.object(rotation, 'ssm_state', return_value=read_state), \
            patch.object(rotation, 'api_request', return_value={'keys': []}) as api:
        revision, result, existing = rotation.preflight(admin_key, 'homelab', receipt)
        assert revision == 'a' * 40 and result == read_state and existing is None
        assert api.call_args.args == ('/tailnet/-/keys',)
        assert api.call_args.kwargs == {'bearer': admin_key}

    # A failed or interrupted POST leaves an ambiguous receipt and cannot mint twice.
    state = {name: {'Version': 2} for name in rotation.PARAMETERS}
    with patch.object(rotation, 'current_main', return_value='a' * 40), \
            patch.object(rotation, 'api_request', side_effect=RuntimeError(new_secret)) as api:
        try:
            rotation.create_client(admin_key, 'a' * 40, state, receipt)
            raise AssertionError('Failed create accepted')
        except RuntimeError:
            pass
        assert api.call_count == 1
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert rotation.read_receipt(receipt)['phase'] == 'creating'
    with patch.object(rotation, 'read_api_key', return_value=admin_key), \
            patch.object(rotation, 'receipt_path', return_value=receipt), \
            patch.object(rotation, 'preflight', return_value=('a' * 40, state, rotation.read_receipt(receipt))), \
            patch.object(rotation, 'api_request') as api, \
            contextlib.redirect_stderr(io.StringIO()) as error:
        assert rotation.main(['rotate', '--api-key-file', str(key_file), '--receipt', str(receipt),
                              '--aws-profile', 'homelab']) == 1
        assert not api.called
        assert new_secret not in error.getvalue()
    receipt.unlink()

    def created(path, **kwargs):
        assert path == '/tailnet/-/keys'
        assert kwargs['method'] == 'POST'
        assert kwargs['bearer'] == admin_key
        assert kwargs['body']['keyType'] == 'client'
        assert kwargs['body']['scopes'] == list(rotation.SCOPES)
        assert kwargs['body']['tags'] == [rotation.TAG]
        return {'keyType': 'client', 'id': new_id, 'key': new_secret,
                'scopes': list(rotation.SCOPES), 'tags': [rotation.TAG]}

    with patch.object(rotation, 'current_main', return_value='a' * 40), \
            patch.object(rotation, 'api_request', side_effect=created):
        record = rotation.create_client(admin_key, 'a' * 40, state, receipt)
    assert record['phase'] == 'created'
    assert rotation.read_receipt(receipt)['client_secret'] == new_secret
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600

    with patch.object(rotation, 'api_request', return_value={'access_token': 'fixture-token',
                                                              'token_type': 'Bearer',
                                                              'scope': 'devices:core auth_keys services'}) as api:
        rotation.verify_new_client(record)
        assert api.call_args.kwargs['basic'] == (new_id, new_secret)
        assert api.call_args.kwargs['body']['tags'] == rotation.TAG
    with patch.object(rotation, 'api_request', return_value={'access_token': 'fixture-token',
                                                              'token_type': 'Bearer', 'scope': 'devices:core'}):
        try:
            rotation.verify_new_client(record)
            raise AssertionError('Missing Services scope accepted')
        except RuntimeError:
            pass

    values = dict(old)
    versions = {'client_id': 2, 'client_secret': 2}
    writes = []

    def fake_aws(profile, action, *args):
        assert profile == 'homelab'
        if action == 'get-parameter':
            parameter = args[args.index('--name') + 1]
            name = next(key for key, value in rotation.PARAMETERS.items() if value == parameter)
            return {'Parameter': {'Name': parameter, 'Type': 'SecureString',
                                  'Version': versions[name], 'Value': values[name]}}
        if action == 'put-parameter':
            path = Path(args[args.index('--cli-input-json') + 1].removeprefix('file://'))
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
            payload = json.loads(path.read_text())
            assert payload['Type'] == 'SecureString'
            assert payload['KeyId'] == 'alias/aws/ssm'
            assert payload['Name'] in rotation.PARAMETERS.values()
            assert new_secret not in str(args)
            name = next(key for key, value in rotation.PARAMETERS.items() if value == payload['Name'])
            values[name] = payload['Value']
            versions[name] += 1
            writes.append(name)
            return {'Version': versions[name]}
        raise AssertionError(action)

    with patch.object(rotation, 'aws', side_effect=fake_aws):
        rotation.transfer('homelab', record, receipt)
        assert writes == ['client_secret', 'client_id']
        assert rotation.read_receipt(receipt)['phase'] == 'stored'
        rotation.transfer('homelab', record, receipt)
        assert writes == ['client_secret', 'client_id']  # retry is idempotent

    # A competing SSM write aborts before replacement.
    values['client_id'] = 'other-client'
    versions['client_id'] += 1
    with patch.object(rotation, 'aws', side_effect=fake_aws):
        try:
            rotation.transfer('homelab', record, receipt)
            raise AssertionError('Competing SSM update accepted')
        except RuntimeError:
            pass
    assert writes == ['client_secret', 'client_id']

    # A command failure must discard private stdout/stderr; AWS env cannot steer the profile.
    with patch.dict(rotation.os.environ, {'AWS_ENDPOINT_URL': 'http://invalid',
                                          'AWS_SECRET_ACCESS_KEY': new_secret}), \
            patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1,
                                                                                      new_secret, new_secret)) as run:
        try:
            rotation.command(['aws', 'ssm', 'get-parameter'])
            raise AssertionError('Failed command accepted')
        except RuntimeError as error:
            assert new_secret not in str(error)
        assert 'AWS_ENDPOINT_URL' not in run.call_args.kwargs['env']
        assert 'AWS_SECRET_ACCESS_KEY' not in run.call_args.kwargs['env']

print('Tailscale operator OAuth rotation containment and resume checks passed')
