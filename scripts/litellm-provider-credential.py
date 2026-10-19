#!/usr/bin/env python3
"""Inject a protected OpenRouter credential into one fixed SSM SecureString."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request

PARAMETER = '/homelab/litellm/openai-api-key'
ENTERPRISE_PARAMETER = '/homelab/openclaw-enterprise/model-api-key'
REGION = 'us-west-2'
ROOT = Path(__file__).resolve().parents[1]


def command(args):
    env = {k: v for k, v in os.environ.items()
           if k not in ('LITELLM_OPENROUTER_API_KEY', 'OCE_MODEL_API_KEY')
           and not k.startswith('AWS_ENDPOINT_URL')}
    env.update(AWS_IGNORE_CONFIGURED_ENDPOINT_URLS='true', AWS_PAGER='')
    result = subprocess.run(args, capture_output=True, text=True, timeout=60, cwd=ROOT, env=env)
    if result.returncode:
        raise RuntimeError('Command failed; private output withheld')
    return result.stdout


def validate_context():
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_REPOSITORY') != 'Stuhlmuller/homelab'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'):
        raise RuntimeError('Protected workflow required')
    sha = os.environ.get('GITHUB_SHA', '')
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise RuntimeError('Invalid revision')
    if command(['git', 'rev-parse', 'HEAD']).strip() != sha:
        raise RuntimeError('Checkout mismatch')
    if command(['git', 'ls-remote', 'https://github.com/Stuhlmuller/homelab.git', 'refs/heads/main']).split() != [sha, 'refs/heads/main']:
        raise RuntimeError('Stale dispatch')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Provider redirect rejected')


def store(key, parameter=PARAMETER):
    with tempfile.TemporaryDirectory(prefix='openrouter-ssm-') as directory:
        path = Path(directory) / 'parameter.json'
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            json.dump({'Name': parameter, 'Type': 'SecureString', 'KeyId': 'alias/aws/ssm',
                       'Value': key, 'Overwrite': True}, stream)
        return json.loads(command(['aws', 'ssm', 'put-parameter', '--region', REGION,
                                   '--cli-input-json', f'file://{path}', '--output', 'json']))


def rotate():
    targets = {
        (): (PARAMETER, 'LITELLM_OPENROUTER_API_KEY'),
        ('--openclaw-enterprise',): (ENTERPRISE_PARAMETER, 'OCE_MODEL_API_KEY'),
    }
    try:
        parameter, secret_name = targets[tuple(sys.argv[1:])]
    except KeyError as error:
        raise RuntimeError('Unsupported fixed credential target') from error
    key = os.environ.pop(secret_name, '')
    if not re.fullmatch(r'sk-or-v1-[a-f0-9]{64}', key):
        raise RuntimeError('Invalid provider credential')
    validate_context()
    metadata = json.loads(command(['aws', 'ssm', 'describe-parameters', '--region', REGION,
                                  '--parameter-filters', f'Key=Name,Option=Equals,Values={parameter}',
                                  '--output', 'json'])).get('Parameters', [])
    if (len(metadata) != 1 or metadata[0].get('Name') != parameter
            or metadata[0].get('Type') != 'SecureString'
            or metadata[0].get('KeyId') != 'alias/aws/ssm'):
        raise RuntimeError('Declared SecureString required')
    request = urllib.request.Request('https://openrouter.ai/api/v1/key',
                                     headers={'Authorization': 'Bearer ' + key})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
        data = json.loads(response.read(1048576))['data']
    if not isinstance(data, dict) or not isinstance(data.get('label'), str):
        raise RuntimeError('Provider validation failed')
    validate_context()
    result = store(key, parameter)
    version = result.get('Version')
    if type(version) is not int or version < 1:
        raise RuntimeError('Uncertain write result')
    if parameter == PARAMETER:
        print(f'OpenRouter credential validated; bootstrap SSM version {version} stored. Advance the GitOps ExternalSecret revision; an already-imported UI credential is unchanged.')
    else:
        print(f'OpenRouter credential validated; Enterprise SSM version {version} stored. Advance the GitOps ExternalSecret revision before using the key.')


def main():
    try:
        rotate()
    except Exception:
        # HTTP/subprocess errors may echo secrets. Never print exception bodies.
        print('OpenRouter credential transfer failed; private details withheld.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
