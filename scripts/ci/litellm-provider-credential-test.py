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

source = Path(__file__).resolve().parents[1] / 'litellm-provider-credential.py'
spec = importlib.util.spec_from_file_location('credential', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
key = 'sk-or-v1-' + 'a' * 64
paths = []


def inspect(args):
    path = Path(args[args.index('--cli-input-json') + 1].removeprefix('file://'))
    paths.append(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert key not in str(args)
    payload = json.loads(path.read_text())
    assert payload == {'Name': '/homelab/litellm/openai-api-key', 'Type': 'SecureString',
                       'KeyId': 'alias/aws/ssm', 'Value': key, 'Overwrite': True}
    return '{"Version":3}'


with patch.object(module, 'command', side_effect=inspect):
    assert module.store(key) == {'Version': 3}
assert all(not path.exists() for path in paths)
with patch.dict(os.environ, {'LITELLM_OPENROUTER_API_KEY': key, 'AWS_ENDPOINT_URL': 'http://invalid'}), \
        patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, key, key)) as run:
    try:
        module.command(['aws', 'ssm', 'put-parameter'])
        raise AssertionError('Failure accepted')
    except RuntimeError as error:
        assert key not in str(error)
    assert 'LITELLM_OPENROUTER_API_KEY' not in run.call_args.kwargs['env']
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
try:
    module.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://invalid')
    raise AssertionError('Redirect accepted')
except RuntimeError:
    pass
print('LiteLLM credential containment checks passed')
