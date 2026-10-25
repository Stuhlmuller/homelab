#!/usr/bin/env python3
"""Create and verify the dedicated, read-only Renovate acceptance GitHub App."""
import sys
if __name__ == '__main__' and not sys.flags.isolated:
    raise SystemExit('Run with python3 -I')

import argparse
import hmac
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REGION = 'us-west-2'
ACCOUNT = '716182248480'
ORG = 'Stuhlmuller'
KEY_ID = 'alias/aws/ssm'
PLACEHOLDER = 'REPLACE_ME'
SSM = {
    'private-key': '/homelab/renovate/acceptance/github-app/private-key',
    'issuer-id': '/homelab/renovate/acceptance/github-app/issuer-id',
}
READ_PERMISSIONS = {name: 'read' for name in (
    'administration', 'checks', 'contents', 'issues', 'members', 'metadata', 'pull_requests',
    'statuses', 'vulnerability_alerts')}
APP_NAME = 'Stuhlmuller Renovate Acceptance Observer'
HOMEPAGE = 'https://github.com/Stuhlmuller/homelab'

spec = importlib.util.spec_from_file_location('github_operator', ROOT / 'scripts' / 'policy-bot-webhook.py')
github = importlib.util.module_from_spec(spec)
spec.loader.exec_module(github)


def aws_command(profile, *arguments, payload=None):
    # A named SSO profile and the fixed AWS endpoint are required. Never put
    # credentials in argv, the environment, a file, or command diagnostics.
    environment = {key: value for key, value in os.environ.items()
                   if key not in {'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
                                  'AWS_SECURITY_TOKEN', 'AWS_ROLE_ARN', 'AWS_WEB_IDENTITY_TOKEN_FILE',
                                  'AWS_PROFILE', 'AWS_DEFAULT_PROFILE'}
                   and not key.startswith('AWS_ENDPOINT_URL')}
    environment.update(AWS_IGNORE_CONFIGURED_ENDPOINT_URLS='true', AWS_PAGER='',
                       AWS_EC2_METADATA_DISABLED='true')
    result = subprocess.run(('aws', '--profile', profile, '--region', REGION, '--no-cli-pager',
                             '--no-cli-auto-prompt', *arguments), input=payload,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
                            cwd=ROOT, timeout=45, check=False)
    if result.returncode:
        raise RuntimeError('AWS SSO metadata or SSM command failed; private output withheld')
    return result.stdout


def sso_preflight(profile):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', profile):
        raise RuntimeError('Choose an existing named AWS SSO profile')
    sso_setting = b''
    for key in ('sso_session', 'sso_start_url'):
        try:
            sso_setting = aws_command(profile, 'configure', 'get', key).strip()
        except RuntimeError:
            continue  # An unset AWS configure key exits nonzero.
        if sso_setting:
            break
    if not sso_setting:
        raise RuntimeError('The named AWS profile must use IAM Identity Center')
    identity = json.loads(aws_command(profile, 'sts', 'get-caller-identity', '--output', 'json'))
    if identity.get('Account') != ACCOUNT or ':assumed-role/AWSReservedSSO_' not in identity.get('Arn', ''):
        raise RuntimeError('Use the expected homelab AWS SSO account')


def ssm_slots(profile, *, require_placeholder):
    names = list(SSM.values())
    metadata = json.loads(aws_command(profile, 'ssm', 'describe-parameters',
                                      '--parameter-filters',
                                      'Key=Name,Option=BeginsWith,Values=/homelab/renovate/acceptance/github-app/',
                                      '--output', 'json')).get('Parameters', [])
    declared = {item.get('Name'): item for item in metadata if item.get('Name') in names}
    if (len(declared) != len(names) or any(
            declared[name].get('Type') != 'SecureString'
            or declared[name].get('Tier') != 'Standard'
            or declared[name].get('KeyId') != KEY_ID for name in names)):
        raise RuntimeError('Both declared Standard SecureString slots are required')
    result = json.loads(aws_command(profile, 'ssm', 'get-parameters', '--names', *names,
                                    '--with-decryption', '--output', 'json'))
    values = {item.get('Name'): item for item in result.get('Parameters', [])}
    if (result.get('InvalidParameters') or len(values) != len(names)
            or any(name not in values for name in names)):
        raise RuntimeError('Acceptance SSM pair is incomplete')
    if require_placeholder and any(values[name].get('Value') != PLACEHOLDER
                                   or values[name].get('Version') != 1 for name in names):
        raise RuntimeError('Acceptance SSM slots must contain only version-one placeholders')
    return values


def manifest(callback_url):
    return {
        'name': APP_NAME,
        'url': HOMEPAGE,
        'description': 'Read-only, temporary acceptance observer for homelab Renovate.',
        'hook_attributes': {'url': HOMEPAGE, 'active': False},
        'redirect_url': callback_url,
        'public': False,
        'default_permissions': READ_PERMISSIONS,
        'default_events': [],
        'request_oauth_on_install': False,
    }


def parse_callback(query, state):
    try:
        values = urllib.parse.parse_qs(query, strict_parsing=True)
    except ValueError:
        raise RuntimeError('Invalid registration callback') from None
    code = values.get('code', [])
    returned_state = values.get('state', [])
    if (set(values) != {'code', 'state'} or len(code) != 1 or len(returned_state) != 1
            or not hmac.compare_digest(returned_state[0], state)
            or not re.fullmatch(r'[A-Za-z0-9_-]{20,256}', code[0])):
        raise RuntimeError('Invalid registration callback')
    return code[0]


def callback_code():
    state = secrets.token_urlsafe(32)
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            pass

        def reply(self, status, body):
            content = body.encode()
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            host = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != host:
                self.reply(400, 'Invalid local host')
                return
            path = urllib.parse.urlsplit(self.path)
            if path.path == '/' and not path.query:
                app_manifest = json.dumps(manifest(f'http://{host}/callback'), separators=(',', ':'))
                action = (f'https://github.com/organizations/{ORG}/settings/apps/new'
                          f'?state={urllib.parse.quote(state)}')
                form = (f'<form action="{action}" method="post">'
                        f'<input type="hidden" name="manifest" value="{html.escape(app_manifest, quote=True)}">'
                        '<button type="submit">Create read-only acceptance App</button></form>')
                self.reply(200, form)
                return
            if path.path != '/callback':
                self.reply(404, 'Not found')
                return
            try:
                code = parse_callback(path.query, state)
            except RuntimeError:
                self.reply(400, 'Invalid registration callback')
                return
            received.append(code)
            self.reply(200, 'Registration received. Return to the terminal to finish validation.')

    with HTTPServer(('127.0.0.1', 0), Handler) as server:
        server.timeout = 1
        print(f'Open http://127.0.0.1:{server.server_port}/ in your browser and approve the org App registration.')
        deadline = time.monotonic() + 3600
        while not received and time.monotonic() < deadline:
            server.handle_request()
    if not received:
        raise RuntimeError('The GitHub App manifest callback timed out')
    return received[0]


def exchange(code):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), github.NoRedirect())
    request = urllib.request.Request(
        f'https://api.github.com/app-manifests/{code}/conversions', data=b'', method='POST',
        headers={'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2026-03-10',
                 'User-Agent': 'homelab-renovate-acceptance-app'})
    try:
        with opener.open(request, timeout=20) as response:
            if response.status != 201:
                raise RuntimeError('GitHub App conversion returned an unexpected status')
            body = response.read(32769)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'GitHub App conversion failed with HTTP {error.code}; response withheld') from None
    if len(body) > 32768:
        raise RuntimeError('GitHub App conversion response is too large')
    return json.loads(body)


def validate_registration(app_id, private_key):
    if type(app_id) is not int or app_id <= 0 or not isinstance(private_key, str):
        raise RuntimeError('GitHub returned an invalid App identity')
    pem_labels = ('RSA PRIVATE KEY', 'PRIVATE KEY')
    pem_markers = ((f'-----BEGIN {label}-----', f'-----END {label}-----')
                   for label in pem_labels)
    if (len(private_key.encode()) > 4096 or not any(
            private_key.startswith(start) and private_key.rstrip().endswith(end)
            for start, end in pem_markers)):
        raise RuntimeError('GitHub returned an invalid Standard SecureString-sized PEM')
    api = github.github_client(github.app_jwt(str(app_id), private_key.encode()))
    registration = api('GET', '/app')
    if (registration.get('id') != app_id
            or registration.get('name') != APP_NAME
            or registration.get('owner', {}).get('login', '').lower() != ORG.lower()
            or registration.get('owner', {}).get('type') != 'Organization'
            or registration.get('permissions') != READ_PERMISSIONS
            or registration.get('events') != []
            or registration.get('slug') == 'rstuhlmuller-renovate'
            or not re.fullmatch(r'[a-z0-9-]{1,100}', registration.get('slug', ''))):
        raise RuntimeError('Dedicated organization App must have exactly the declared read grants and no events')
    return api, registration['slug']


def validate_installation(api, app_id):
    installation = api('GET', f'/orgs/{ORG}/installation')
    if (installation.get('app_id') != app_id
            or installation.get('account', {}).get('login', '').lower() != ORG.lower()
            or installation.get('repository_selection') != 'all'
            or installation.get('permissions') != READ_PERMISSIONS):
        raise RuntimeError('Dedicated App must be installed for all organization repositories with read grants')


def put_parameter(profile, name, value):
    result = json.loads(aws_command(profile, 'ssm', 'put-parameter', '--name', name,
                                    '--type', 'SecureString', '--key-id', KEY_ID,
                                    '--value', 'file:///dev/stdin', '--overwrite',
                                    '--output', 'json', payload=value.encode()))
    if type(result.get('Version')) is not int or result['Version'] != 2:
        raise RuntimeError('Acceptance SSM write lacks the expected version-two receipt')


def resume_transfer(profile, expected_sha, app_id, values):
    """Finish only a validated key-v2/issuer-v1 transfer; accept a lost receipt."""
    key = values[SSM['private-key']]
    issuer = values[SSM['issuer-id']]
    if key.get('Version') != 2:
        raise RuntimeError('Only the first acceptance key write can be resumed')
    _, slug = validate_registration(app_id, key.get('Value'))
    if issuer.get('Version') == 2 and issuer.get('Value') == str(app_id):
        print(f'Acceptance App {app_id} transfer already completed (version 2). '
              f'Install for all repositories: https://github.com/apps/{slug}/installations/new')
        return
    if issuer.get('Version') != 1 or issuer.get('Value') != PLACEHOLDER:
        raise RuntimeError('Acceptance issuer slot is not the initial placeholder')
    github.verify_reviewed_main(expected_sha)
    if ssm_slots(profile, require_placeholder=False) != values:
        raise RuntimeError('Acceptance SSM slots changed during recovery')
    put_parameter(profile, SSM['issuer-id'], str(app_id))
    print(f'Acceptance App {app_id} transfer completed (version 2). '
          f'Install for all repositories: https://github.com/apps/{slug}/installations/new')


def run(args):
    github.verify_reviewed_main(args.expected_sha)
    sso_preflight(args.profile)
    values = ssm_slots(args.profile, require_placeholder=args.action == 'create')
    if (args.action == 'resume') != (args.app_id is not None):
        raise RuntimeError('Only resume accepts a public App ID')
    if args.action == 'create':
        code = callback_code()
        github.verify_reviewed_main(args.expected_sha)
        converted = exchange(code)
        app_id = converted.get('id')
        private_key = converted.get('pem')
        _, slug = validate_registration(app_id, private_key)
        # A verified public ID lets the operator resume if only the key write
        # succeeds. Flush before either SSM write so a later failure cannot
        # hide the identity needed for exact-target recovery.
        print(f'Validated acceptance App ID {app_id} ({slug}); '
              'record this public ID for transfer recovery.', flush=True)
        # Recheck immediately before mutation; first write the key, then the
        # issuer. A partial failure cannot activate an observer by itself.
        github.verify_reviewed_main(args.expected_sha)
        ssm_slots(args.profile, require_placeholder=True)
        put_parameter(args.profile, SSM['private-key'], private_key)
        put_parameter(args.profile, SSM['issuer-id'], str(app_id))
        print(f'App credentials stored in the two acceptance SSM slots (version 2). '
              f'Install for all repositories: https://github.com/apps/{slug}/installations/new')
    elif args.action == 'resume':
        resume_transfer(args.profile, args.expected_sha, args.app_id, values)
    else:
        issuer = values[SSM['issuer-id']]
        key = values[SSM['private-key']]
        if (issuer.get('Version', 0) < 2 or key.get('Version', 0) < 2
                or not str(issuer.get('Value', '')).isdigit()):
            raise RuntimeError('Dedicated App credentials have not replaced both placeholders')
        app_id = int(issuer['Value'])
        api, slug = validate_registration(app_id, key['Value'])
        validate_installation(api, app_id)
        print(f'Read-only acceptance App {app_id} ({slug}) and all-repositories '
              'organization installation verified.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, help='existing AWS IAM Identity Center profile')
    parser.add_argument('--expected-sha', required=True, help='full reviewed remote main commit')
    parser.add_argument('--app-id', type=int, help='public App ID, required only for resume')
    parser.add_argument('action', choices=('create', 'resume', 'verify'))
    try:
        run(parser.parse_args())
    except Exception:
        raise SystemExit('Renovate acceptance App operation failed; private details withheld') from None
