#!/usr/bin/env python3
"""Offline checks for credential containment and fixed SSM destination."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
from unittest.mock import patch

source = Path(__file__).resolve().parents[1] / 'mastodon-smtp-credential.py'
spec = importlib.util.spec_from_file_location('credential', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
key = 'fixture-password-with-special-characters#=$'
paths = []


def inspect(args):
    path = Path(args[args.index('--cli-input-json') + 1].removeprefix('file://'))
    paths.append(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert key not in str(args)
    payload = json.loads(path.read_text())
    assert payload == {'Name': '/homelab/mastodon/smtp-password', 'Type': 'SecureString',
                       'KeyId': 'alias/aws/ssm', 'Value': key, 'Overwrite': True}
    return '{"Version":3}'


with patch.object(module, 'command', side_effect=inspect):
    assert module.store(key) == {'Version': 3}
assert all(not path.exists() for path in paths)
with patch.dict(os.environ, {'MASTODON_SMTP_PASSWORD': key, 'AWS_ENDPOINT_URL': 'http://invalid'}), \
        patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, key, key)) as run:
    try:
        module.command(['aws', 'ssm', 'put-parameter'])
        raise AssertionError('Failure accepted')
    except RuntimeError as error:
        assert key not in str(error)
    assert 'MASTODON_SMTP_PASSWORD' not in run.call_args.kwargs['env']
    assert 'AWS_ENDPOINT_URL' not in run.call_args.kwargs['env']
with patch.object(module, 'rotate', side_effect=RuntimeError(key)), contextlib.redirect_stderr(io.StringIO()) as output:
    assert module.main() == 1
    assert key not in output.getvalue()
with patch.dict(os.environ, {}, clear=True), patch.object(module, 'command') as command:
    try:
        module.validate_context()
        raise AssertionError('Local context accepted')
    except RuntimeError:
        assert not command.called
for invalid in ['', 'REPLACE_ME', 'x' * 4097]:
    with patch.dict(os.environ, {'MASTODON_SMTP_PASSWORD': invalid}), \
            patch.object(module, 'validate_context') as context:
        try:
            module.rotate()
            raise AssertionError('Invalid credential accepted')
        except RuntimeError:
            assert not context.called
metadata = {'Parameters': [{'Name': module.PARAMETER, 'Type': 'SecureString', 'KeyId': 'alias/aws/ssm'}]}
with patch.dict(os.environ, {'MASTODON_SMTP_PASSWORD': key}), \
        patch.object(module, 'validate_context') as context, \
        patch.object(module, 'command', return_value=json.dumps(metadata)), \
        patch.object(module, 'store', return_value={'Version': 3}) as store, \
        contextlib.redirect_stdout(io.StringIO()) as output:
    module.rotate()
    store.assert_called_once_with(key)
    assert context.call_count == 2
    assert key not in output.getvalue()
metadata['Parameters'][0]['Name'] = '/homelab/fleet/mysql-root-password'
with patch.dict(os.environ, {'MASTODON_SMTP_PASSWORD': key}), \
        patch.object(module, 'validate_context'), \
        patch.object(module, 'command', return_value=json.dumps(metadata)), \
        patch.object(module, 'store') as store:
    try:
        module.rotate()
        raise AssertionError('Wrong parameter metadata accepted')
    except RuntimeError:
        assert not store.called
print('Mastodon SMTP credential containment and input checks passed')
