#!/usr/bin/env python3
"""One-shot, resumable transfer of a new Tailscale operator OAuth client to SSM.

The API key and newly minted client secret are never accepted as arguments or
written to stdout. This command does not refresh the Kubernetes Secret.
"""

import argparse
import base64
import hmac
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
REGION = 'us-west-2'
API = 'https://api.tailscale.com/api/v2'
PARAMETERS = {
    'client_id': '/homelab/tailscale/oauth-client-id',
    'client_secret': '/homelab/tailscale/oauth-client-secret',
}
SCOPES = ('devices:core', 'auth_keys', 'services')
TAG = 'tag:k8s-operator'
DESCRIPTION_PREFIX = 'homelab-k8s-operator-'


def private_file(path, *, must_exist=True):
    """Reject symlinks and shared files before loading private material."""
    path = Path(path).expanduser().absolute()
    # Resolve ancestors before the repo boundary check; the final path remains
    # lexical so lstat can still reject a symlinked key or receipt itself.
    if path.parent.resolve().is_relative_to(ROOT):
        raise RuntimeError('Private file must be outside the repository')
    if must_exist:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise RuntimeError('Private file must be regular and mode 0600')
    return path


def read_api_key(path):
    path = private_file(path)
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or stat.S_IMODE(parent.st_mode) != 0o700:
        raise RuntimeError('API key directory must be mode 0700')
    key = path.read_text().strip()
    if not key.startswith('tskey-api-') or len(key) > 4096 or '\n' in key:
        raise RuntimeError('Owner/Admin Tailscale API key file required')
    return key


def receipt_path(path):
    path = private_file(path, must_exist=False)
    parent = path.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError('Receipt directory must be mode 0700')
    if path.exists() or path.is_symlink():
        private_file(path)
    return path


def read_receipt(path):
    if not path.exists():
        return None
    private_file(path)
    data = json.loads(path.read_text())
    if data.get('schema') != 1 or data.get('phase') not in ('creating', 'created', 'stored'):
        raise RuntimeError('Invalid receipt')
    return data


def save_receipt(path, data, *, first=False):
    payload = json.dumps(data, sort_keys=True).encode() + b'\n'
    if first:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        with os.fdopen(os.open(path, flags, 0o600), 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.oauth-receipt-', delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def command(args):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('AWS_') and key not in ('GITHUB_TOKEN', 'GH_TOKEN')}
    env.update(AWS_PAGER='', AWS_IGNORE_CONFIGURED_ENDPOINT_URLS='true', AWS_CLI_AUTO_PROMPT='off')
    result = subprocess.run(args, cwd=ROOT, env=env, text=True,
                            capture_output=True, timeout=60, check=False)
    if result.returncode:
        raise RuntimeError('Command failed; private output withheld')
    return result.stdout


def current_main():
    if command(['git', 'status', '--porcelain']).strip():
        raise RuntimeError('Clean checkout required')
    revision = command(['git', 'rev-parse', 'HEAD']).strip()
    remote = command(['git', 'ls-remote', 'https://github.com/Stuhlmuller/homelab.git',
                      'refs/heads/main']).split()
    if not re.fullmatch('[0-9a-f]{40}', revision) or remote != [revision, 'refs/heads/main']:
        raise RuntimeError('Current main checkout required')
    return revision


def validate_contract():
    source = (ROOT / 'clusters/homelab/apps/tailscale/externalsecret.yaml').read_text()
    if ('refreshPolicy: OnChange' not in source
            or any(value not in source for value in PARAMETERS.values())
            or 'name: operator-oauth' not in source):
        raise RuntimeError('Operator ExternalSecret contract changed')
    policy = json.loads((ROOT / 'scripts/config/tailscale-policy.json').read_text())
    owners = policy.get('tagOwners', {})
    if owners.get(TAG) != [] or 'tag:k8s-operator' not in owners.get('tag:k8s', []):
        raise RuntimeError('Operator tag ownership changed')


def aws(profile, *args):
    return json.loads(command(['aws', '--profile', profile, 'ssm', *args,
                               '--region', REGION, '--output', 'json']))


def ssm_state(profile):
    state = {}
    for name, parameter in PARAMETERS.items():
        items = aws(profile, 'describe-parameters', '--parameter-filters',
                    f'Key=Name,Option=Equals,Values={parameter}').get('Parameters', [])
        if (len(items) != 1 or items[0].get('Name') != parameter
                or items[0].get('Type') != 'SecureString'
                or items[0].get('KeyId') != 'alias/aws/ssm'):
            raise RuntimeError('Declared SecureString required')
        item = aws(profile, 'get-parameter', '--name', parameter,
                   '--with-decryption').get('Parameter', {})
        if (item.get('Name') != parameter or item.get('Type') != 'SecureString'
                or type(item.get('Version')) is not int or item['Version'] < 1
                or not isinstance(item.get('Value'), str)):
            raise RuntimeError('SSM readback failed')
        state[name] = item
    return state


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward an API key or client secret to a redirected origin."""

    def redirect_request(self, request, response, code, message, headers, url):
        raise RuntimeError('Credentialed Tailscale API redirect refused')


def api_request(path, *, method='GET', bearer=None, body=None, basic=None):
    headers = {'Accept': 'application/json'}
    if bearer is not None:
        headers['Authorization'] = f'Bearer {bearer}'
    if basic is not None:
        encoded = base64.b64encode(f'{basic[0]}:{basic[1]}'.encode()).decode()
        headers['Authorization'] = f'Basic {encoded}'
    data = None
    if body is not None:
        if isinstance(body, dict):
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        else:
            data = urllib.parse.urlencode(body).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
    request = urllib.request.Request(f'{API}{path}', data=data, headers=headers, method=method)
    # The default opener reads proxy environment variables and carries
    # Authorization to redirect targets. Neither is safe for these credentials.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), RefuseRedirect())
    with opener.open(request, timeout=20) as response:
        return json.load(response)


def preflight(api_key, profile, path):
    revision = current_main()
    validate_contract()
    state = ssm_state(profile)
    listing = api_request('/tailnet/-/keys', bearer=api_key)
    if not isinstance(listing.get('keys'), list):
        raise RuntimeError('Tailscale API key read check failed')
    existing = read_receipt(path)
    if existing and existing.get('revision') != revision:
        raise RuntimeError('Receipt belongs to a different main revision')
    return revision, state, existing


def create_client(api_key, revision, state, path):
    if current_main() != revision:
        raise RuntimeError('Main moved during preflight')
    record = {'schema': 1, 'phase': 'creating', 'revision': revision,
              'request_id': uuid4().hex,
              'old_versions': {name: item['Version'] for name, item in state.items()}}
    save_receipt(path, record, first=True)
    result = api_request('/tailnet/-/keys', method='POST', bearer=api_key,
                         body={'keyType': 'client', 'description':
                               DESCRIPTION_PREFIX + record['request_id'][:16],
                               'scopes': list(SCOPES), 'tags': [TAG]})
    if (result.get('keyType') != 'client' or not isinstance(result.get('id'), str)
            or not result['id'] or not isinstance(result.get('key'), str)
            or not result['key'] or set(result.get('scopes', [])) != set(SCOPES)
            or result.get('tags') != [TAG]):
        raise RuntimeError('Unexpected Tailscale create response; receipt requires recovery')
    record.update(phase='created', client_id=result['id'], client_secret=result['key'])
    save_receipt(path, record)
    return record


def verify_new_client(record):
    result = api_request('/oauth/token', method='POST',
                         basic=(record['client_id'], record['client_secret']),
                         body=[('grant_type', 'client_credentials'),
                               ('scope', ' '.join(SCOPES)), ('tags', TAG)])
    if (not isinstance(result.get('access_token'), str) or not result['access_token']
            or str(result.get('token_type', '')).lower() != 'bearer'):
        raise RuntimeError('New OAuth client token check failed')
    if result.get('scope') and not set(SCOPES).issubset(set(result['scope'].split())):
        raise RuntimeError('New OAuth client missing requested scopes')


def put_parameter(profile, parameter, value):
    with tempfile.TemporaryDirectory(prefix='tailscale-oauth-ssm-') as directory:
        path = Path(directory) / 'parameter.json'
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            json.dump({'Name': parameter, 'Type': 'SecureString', 'KeyId': 'alias/aws/ssm',
                       'Value': value, 'Overwrite': True}, stream)
        result = aws(profile, 'put-parameter', '--cli-input-json', f'file://{path}')
    if type(result.get('Version')) is not int or result['Version'] < 1:
        raise RuntimeError('Uncertain SSM write result')


def transfer(profile, record, path):
    # Secret first, ID second. Do not trigger the OnChange consumer until both verify.
    for name in ('client_secret', 'client_id'):
        parameter = PARAMETERS[name]
        expected = record[name]
        current = aws(profile, 'get-parameter', '--name', parameter,
                      '--with-decryption').get('Parameter', {})
        if current.get('Name') != parameter or type(current.get('Version')) is not int:
            raise RuntimeError('SSM readback failed')
        if not hmac.compare_digest(current.get('Value', ''), expected):
            if current['Version'] != record['old_versions'][name]:
                raise RuntimeError('SSM version changed since preflight')
            put_parameter(profile, parameter, expected)
        verify = aws(profile, 'get-parameter', '--name', parameter,
                     '--with-decryption').get('Parameter', {})
        if verify.get('Name') != parameter or not hmac.compare_digest(verify.get('Value', ''), expected):
            raise RuntimeError('SSM write verification failed')
    record['phase'] = 'stored'
    save_receipt(path, record)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('preflight', 'rotate'))
    parser.add_argument('--api-key-file', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--aws-profile', required=True,
                        help='Existing SSM-authorized named AWS profile chosen by the operator')
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', args.aws_profile):
            raise RuntimeError('Invalid AWS profile name')
        key = read_api_key(args.api_key_file)
        path = receipt_path(args.receipt)
        revision, state, record = preflight(key, args.aws_profile, path)
        if args.action == 'preflight':
            print('Operator OAuth preflight passed; no writes made.')
            return 0
        if record and record['phase'] == 'creating':
            raise RuntimeError('Creation outcome uncertain; inspect or revoke the request ID before recovery')
        if not record:
            record = create_client(key, revision, state, path)
        if record['phase'] not in ('created', 'stored'):
            raise RuntimeError('Invalid receipt phase')
        verify_new_client(record)
        transfer(args.aws_profile, record, path)
        print('Operator OAuth pair verified in SSM. Advance ExternalSecret and operator revisions by reviewed GitOps change.')
        return 0
    except Exception:
        # HTTP, AWS, and subprocess exceptions can include request bodies or credentials.
        print('Operator OAuth rotation stopped; private details withheld. Inspect the private receipt.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
