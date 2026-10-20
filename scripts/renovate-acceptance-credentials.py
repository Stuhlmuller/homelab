#!/usr/bin/env python3
"""Validate one read-only GitHub App and store its acceptance-only SSM pair."""
import sys
if __name__ == '__main__' and not sys.flags.isolated:
    raise SystemExit('Run with python3 -I')

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REGION = 'us-west-2'
KEY_ID = 'alias/aws/ssm'
PARAMETERS = {
    'RENOVATE_ACCEPTANCE_APP_ISSUER_ID': '/homelab/renovate/acceptance/github-app/issuer-id',
    'RENOVATE_ACCEPTANCE_APP_PRIVATE_KEY': '/homelab/renovate/acceptance/github-app/private-key',
}
READ_PERMISSIONS = frozenset(('checks', 'contents', 'issues', 'members', 'metadata',
                              'pull_requests', 'statuses', 'vulnerability_alerts'))

spec = importlib.util.spec_from_file_location('github_operator', ROOT / 'scripts' / 'policy-bot-webhook.py')
github = importlib.util.module_from_spec(spec)
spec.loader.exec_module(github)


def command(*args, env):
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, timeout=45, check=False)
    if result.returncode:
        raise RuntimeError('Credential metadata or storage command failed; private output withheld')
    return result.stdout


def context():
    expected = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'Stuhlmuller/homelab',
                'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                'GITHUB_WORKFLOW_REF':
                'Stuhlmuller/homelab/.github/workflows/renovate-acceptance-credentials.yml@refs/heads/main'}
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise RuntimeError('Protected current-main workflow required')
    github.verify_reviewed_main(os.environ.get('GITHUB_SHA'))


def read_grants(permissions):
    return (isinstance(permissions, dict) and READ_PERMISSIONS <= permissions.keys()
            and all(value == 'read' for value in permissions.values()))


def validate_app(issuer, private_key):
    app = github.github_client(github.app_jwt(issuer, private_key.encode()))
    registration = app('GET', '/app')
    if (issuer not in (str(registration.get('id')), registration.get('client_id'))
            or registration.get('slug') == 'rstuhlmuller-renovate'
            or not read_grants(registration.get('permissions'))):
        raise RuntimeError('Read-only App identity and permissions required')
    installation = app('GET', '/orgs/Stuhlmuller/installation')
    if (installation.get('app_id') != registration['id']
            or installation.get('account', {}).get('login', '').lower() != 'stuhlmuller'
            or installation.get('repository_selection') != 'all'
            or not read_grants(installation.get('permissions'))):
        raise RuntimeError('Read-only all-repositories installation required')


def inject():
    if len(sys.argv) != 1:
        raise RuntimeError('This fixed credential workflow accepts no arguments')
    values = {key: os.environ.pop(key, '') for key in PARAMETERS}
    context()
    issuer, private_key = values.values()
    pem_markers = (('-----BEGIN RSA PRIVATE KEY-----', '-----END RSA PRIVATE KEY-----'),
                   ('-----BEGIN PRIVATE KEY-----', '-----END PRIVATE KEY-----'))
    if (not issuer or len(issuer) > 128 or '\n' in issuer or '\r' in issuer
            or not any(private_key.startswith(start) and private_key.rstrip().endswith(end)
                       for start, end in pem_markers)
            or len(private_key.encode()) > 4096):
        raise RuntimeError('Expected one GitHub App issuer and Standard SecureString-sized PEM')
    validate_app(issuer, private_key)
    environment = {key: value for key, value in os.environ.items()
                   if key not in {'GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN'}
                   and not key.startswith('AWS_ENDPOINT_URL')}
    environment.update(AWS_IGNORE_CONFIGURED_ENDPOINT_URLS='true', AWS_PAGER='')
    for name in PARAMETERS.values():
        metadata = json.loads(command('aws', 'ssm', 'describe-parameters', '--region', REGION,
                                      '--parameter-filters', f'Key=Name,Option=Equals,Values={name}',
                                      '--output', 'json', env=environment)).get('Parameters', [])
        if (len(metadata) != 1 or metadata[0].get('Name') != name
                or metadata[0].get('Type') != 'SecureString'
                or metadata[0].get('KeyId') != KEY_ID or metadata[0].get('Tier') != 'Standard'):
            raise RuntimeError('Declared acceptance SecureString slots required')
    versions = []
    with tempfile.TemporaryDirectory(prefix='renovate-acceptance-intake-') as directory:
        for key, name in PARAMETERS.items():
            context()
            path = Path(directory) / 'parameter.json'
            with open(path, 'w', opener=lambda target, flags: os.open(target, flags, 0o600)) as output:
                json.dump({'Name': name, 'Type': 'SecureString', 'KeyId': KEY_ID,
                           'Value': values[key], 'Overwrite': True}, output)
            result = json.loads(command('aws', 'ssm', 'put-parameter', '--region', REGION,
                                        '--cli-input-json', 'file://' + str(path), '--output', 'json',
                                        env=environment))
            path.unlink()
            if type(result.get('Version')) is not int or result['Version'] < 2:
                raise RuntimeError('Credential write lacks a post-placeholder version receipt')
            versions.append(result['Version'])
    print(f'Read-only App credential pair stored; SSM versions {versions[0]} and {versions[1]}.')


if __name__ == '__main__':
    try:
        inject()
    except Exception:
        raise SystemExit('Renovate acceptance credential intake failed; private details withheld') from None
