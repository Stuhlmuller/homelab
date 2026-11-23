#!/usr/bin/env python3
"""Inject one Deluge VPN path bundle into its three declared SSM slots."""

import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'Stuhlmuller/homelab'
REGION = 'us-west-2'
KEY_ID = 'alias/aws/ssm'
BUNDLE_ENV = 'DELUGE_VPN_BUNDLE'
SLOTS = ('airvpn-profile', 'gateway-transit', 'client-transit')


@contextmanager
def private_file(content):
    with tempfile.TemporaryDirectory(prefix='deluge-vpn-ssm-') as directory:
        path = Path(directory) / 'credential'
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as stream:
            stream.write(content)
        yield path


def command(args, *, input=None):
    env = {name: value for name, value in os.environ.items()
           if name != BUNDLE_ENV and not name.startswith('AWS_ENDPOINT_URL')}
    env.update(AWS_IGNORE_CONFIGURED_ENDPOINT_URLS='true', AWS_PAGER='')
    result = subprocess.run(args, input=input, capture_output=True, text=True, timeout=60, cwd=ROOT, env=env)
    if result.returncode:
        raise RuntimeError('Command failed. Private output withheld.')
    return result.stdout


def validate_context():
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_REPOSITORY') != REPOSITORY
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'):
        raise RuntimeError('Protected workflow required')
    sha = os.environ.get('GITHUB_SHA', '')
    if not re.fullmatch('[0-9a-f]{40}', sha) or sha != os.environ.get('EXPECTED_SHA'):
        raise RuntimeError('Invalid revision')
    if command(['git', 'rev-parse', 'HEAD']).strip() != sha:
        raise RuntimeError('Checkout mismatch')
    if command(['git', 'ls-remote', f'https://github.com/{REPOSITORY}.git', 'refs/heads/main']).split() != [sha, 'refs/heads/main']:
        raise RuntimeError('Stale dispatch')


def unique_object(entries):
    result = {}
    for key, value in entries:
        if key in result:
            raise ValueError('Duplicate bundle field')
        result[key] = value
    return result


def wireguard_key(value):
    if not isinstance(value, str) or len(value) != 44:
        raise ValueError('Invalid WireGuard key')
    decoded = base64.b64decode(value, validate=True)
    if len(decoded) != 32 or not any(decoded) or base64.b64encode(decoded).decode() != value:
        raise ValueError('Invalid WireGuard key')
    return value


def validate_bundle(raw):
    if not raw or len(raw.encode()) > 8192:
        raise ValueError('Invalid bundle length')
    bundle = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(bundle, dict) or bundle.keys() != {'airvpn_profile', 'gateway_transit', 'client_transit'}:
        raise ValueError('Invalid bundle fields')
    profile_text = bundle['airvpn_profile']
    if not isinstance(profile_text, str) or not 1 <= len(profile_text.encode()) <= 4096:
        raise ValueError('Invalid AirVPN profile length')
    parse_profile = runpy.run_path(str(ROOT / 'builds/deluge-vpn/network.py'))['read_airvpn_profile']
    with private_file(profile_text) as path:
        profile, airvpn_private, preshared = parse_profile(path)
    wireguard_key(profile.public_key)
    wireguard_key(airvpn_private)
    wireguard_key(preshared)

    client = bundle['client_transit']
    gateway = bundle['gateway_transit']
    for transit in (client, gateway):
        if not isinstance(transit, dict) or transit.keys() != {'private', 'peer_public'}:
            raise ValueError('Invalid transit fields')
        for key in transit.values():
            wireguard_key(key)
    if len({airvpn_private, client['private'], gateway['private']}) != 3:
        raise ValueError('Duplicate device keys')
    for local, remote in ((client, gateway), (gateway, client)):
        public = command(['wg', 'pubkey'], input=local['private'] + '\n').strip()
        if public != remote['peer_public']:
            raise ValueError('Transit key pair mismatch')
    return (profile_text, json.dumps(gateway, separators=(',', ':')), json.dumps(client, separators=(',', ':')))


def require_parameter(name):
    metadata = json.loads(command([
        'aws', 'ssm', 'describe-parameters', '--region', REGION,
        '--parameter-filters', f'Key=Name,Option=Equals,Values={name}', '--output', 'json',
    ])).get('Parameters', [])
    if (len(metadata) != 1 or metadata[0].get('Name') != name
            or metadata[0].get('Type') != 'SecureString' or metadata[0].get('KeyId') != KEY_ID):
        raise RuntimeError('Declared SecureString required')


def store(name, value):
    content = json.dumps({'Name': name, 'Type': 'SecureString', 'KeyId': KEY_ID,
                          'Value': value, 'Overwrite': True})
    with private_file(content) as path:
        response = json.loads(command([
            'aws', 'ssm', 'put-parameter', '--region', REGION,
            '--cli-input-json', f'file://{path}', '--output', 'json',
        ]))
    version = response.get('Version')
    if type(version) is not int or version < 1:
        raise RuntimeError('Uncertain write result')
    return version


def rotate():
    if len(sys.argv) != 2 or sys.argv[1] not in {'a', 'b'}:
        raise ValueError('Select a fixed VPN path')
    path = sys.argv[1]
    raw = os.environ.pop(BUNDLE_ENV, '')
    validate_context()
    values = validate_bundle(raw)
    targets = tuple(f'/homelab/deluge/vpn/{path}/{slot}' for slot in SLOTS)
    for name in targets:
        require_parameter(name)
    validate_context()
    versions = [store(name, value) for name, value in zip(targets, values, strict=True)]
    receipt = ', '.join(f'{slot} version {version}' for slot, version in zip(SLOTS, versions, strict=True))
    print(f'Deluge VPN path {path} stored ({receipt}). Advance ExternalSecret and pod revisions through GitOps.')


def main():
    try:
        rotate()
    except Exception:
        print('Deluge VPN credential transfer failed. Private details withheld.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
