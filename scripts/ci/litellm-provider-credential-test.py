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
import sys
from unittest.mock import patch

source = Path(__file__).resolve().parents[1] / 'litellm-provider-credential.py'
spec = importlib.util.spec_from_file_location('credential', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
key = 'sk-or-v1-' + 'a' * 64
paths = []
expected_parameters = iter((module.PARAMETER, module.ENTERPRISE_PARAMETER))


def inspect(args):
    path = Path(args[args.index('--cli-input-json') + 1].removeprefix('file://'))
    paths.append(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert key not in str(args)
    payload = json.loads(path.read_text())
    assert payload == {'Name': next(expected_parameters), 'Type': 'SecureString',
                       'KeyId': 'alias/aws/ssm', 'Value': key, 'Overwrite': True}
    return '{"Version":3}'


with patch.object(module, 'command', side_effect=inspect):
    assert module.store(key) == {'Version': 3}
    assert module.store(key, module.ENTERPRISE_PARAMETER) == {'Version': 3}
assert all(not path.exists() for path in paths)
with patch.dict(os.environ, {'LITELLM_OPENROUTER_API_KEY': key, 'OCE_MODEL_API_KEY': key,
                             'AWS_ENDPOINT_URL': 'http://invalid'}), \
        patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, key, key)) as run:
    try:
        module.command(['aws', 'ssm', 'put-parameter'])
        raise AssertionError('Failure accepted')
    except RuntimeError as error:
        assert key not in str(error)
    assert 'LITELLM_OPENROUTER_API_KEY' not in run.call_args.kwargs['env']
    assert 'OCE_MODEL_API_KEY' not in run.call_args.kwargs['env']
    assert 'AWS_ENDPOINT_URL' not in run.call_args.kwargs['env']


class ProviderResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return b'{"data":{"label":"enterprise-test"}}'


class ProviderOpener:
    def open(self, request, timeout):
        assert request.full_url == 'https://openrouter.ai/api/v1/key'
        assert request.get_header('Authorization') == 'Bearer ' + key
        return ProviderResponse()


metadata = {'Parameters': [{'Name': module.ENTERPRISE_PARAMETER,
                            'Type': 'SecureString', 'KeyId': 'alias/aws/ssm'}]}
with patch.dict(os.environ, {'OCE_MODEL_API_KEY': key}), \
        patch.object(sys, 'argv', [str(source), '--openclaw-enterprise']), \
        patch.object(module, 'validate_context'), \
        patch.object(module, 'command', return_value=json.dumps(metadata)) as command, \
        patch.object(module.urllib.request, 'build_opener', return_value=ProviderOpener()), \
        patch.object(module, 'store', return_value={'Version': 3}) as store, \
        contextlib.redirect_stdout(io.StringIO()):
    module.rotate()
    assert any(module.ENTERPRISE_PARAMETER in item for item in command.call_args.args[0])
    store.assert_called_once_with(key, module.ENTERPRISE_PARAMETER)
    assert 'OCE_MODEL_API_KEY' not in os.environ

wrong_metadata = {'Parameters': [{'Name': module.PARAMETER,
                                  'Type': 'SecureString', 'KeyId': 'alias/aws/ssm'}]}
with patch.dict(os.environ, {'OCE_MODEL_API_KEY': key}), \
        patch.object(sys, 'argv', [str(source), '--openclaw-enterprise']), \
        patch.object(module, 'validate_context'), \
        patch.object(module, 'command', return_value=json.dumps(wrong_metadata)), \
        patch.object(module, 'store') as store:
    try:
        module.rotate()
        raise AssertionError('Legacy parameter accepted for Enterprise')
    except RuntimeError:
        assert not store.called

with patch.object(sys, 'argv', [str(source), '--arbitrary-parameter']), \
        patch.object(module, 'command') as command:
    try:
        module.rotate()
        raise AssertionError('Arbitrary credential target accepted')
    except RuntimeError:
        assert not command.called
with patch.object(module, 'rotate', side_effect=RuntimeError(key)), contextlib.redirect_stderr(io.StringIO()) as output:
    assert module.main() == 1
    assert key not in output.getvalue()
with patch.dict(os.environ, {}, clear=True), patch.object(module, 'command') as command:
    try:
        module.validate_context()
        raise AssertionError('Local context accepted')
    except RuntimeError:
        assert not command.called
try:
    module.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://invalid')
    raise AssertionError('Redirect accepted')
except RuntimeError:
    pass
print('OpenRouter credential containment checks passed')
