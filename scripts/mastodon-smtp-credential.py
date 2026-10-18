#!/usr/bin/env python3
"""Inject the protected Mastodon SMTP password into its declared SecureString."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

PARAMETER = '/homelab/mastodon/smtp-password'
REGION = 'us-west-2'
ROOT = Path(__file__).resolve().parents[1]


def command(args):
    env = {k: v for k, v in os.environ.items()
           if k != 'MASTODON_SMTP_PASSWORD' and not k.startswith('AWS_ENDPOINT_URL')}
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


def store(key):
    with tempfile.TemporaryDirectory(prefix='mastodon-smtp-ssm-') as directory:
        path = Path(directory) / 'parameter.json'
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            json.dump({'Name': PARAMETER, 'Type': 'SecureString', 'KeyId': 'alias/aws/ssm',
                       'Value': key, 'Overwrite': True}, stream)
        return json.loads(command(['aws', 'ssm', 'put-parameter', '--region', REGION,
                                   '--cli-input-json', f'file://{path}', '--output', 'json']))


def rotate():
    if len(sys.argv) != 1:
        raise RuntimeError('No command-line inputs supported')
    key = os.environ.pop('MASTODON_SMTP_PASSWORD', '')
    if not key or key == 'REPLACE_ME' or len(key.encode('utf-8')) > 4096:
        raise RuntimeError('Invalid SMTP credential')
    validate_context()
    metadata = json.loads(command(['aws', 'ssm', 'describe-parameters', '--region', REGION,
                                  '--parameter-filters', f'Key=Name,Option=Equals,Values={PARAMETER}',
                                  '--output', 'json'])).get('Parameters', [])
    if (len(metadata) != 1 or metadata[0].get('Name') != PARAMETER
            or metadata[0].get('Type') != 'SecureString'
            or metadata[0].get('KeyId') != 'alias/aws/ssm'):
        raise RuntimeError('Declared SecureString required')
    validate_context()
    result = store(key)
    version = result.get('Version')
    if type(version) is not int or version < 1:
        raise RuntimeError('Uncertain write result')
    print(f'Mastodon SMTP password stored as SSM version {version}. Advance the runtime ExternalSecret and Deployment revisions through GitOps, then verify email delivery.')


def main():
    try:
        rotate()
    except Exception:
        # Subprocess errors may echo secrets. Never print exception bodies.
        print('Mastodon SMTP credential transfer failed; private details withheld.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
