#!/usr/bin/env python3
"""Preview or reconcile only Policy Bot's declared GitHub App webhook URL."""
import sys
if __name__ == '__main__' and not sys.flags.isolated:
    raise SystemExit('Run with python3 -I')

import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_URL = 'https://policy-bot-hook.stinkyboi.com/api/github/hook'
URL = 'https://policy-bot-hook.tail67beb.ts.net/api/github/hook'
CONFIG_PATH = '/app/hook/config'
RECEIPT = Path.home() / '.local/state/homelab/policy-bot-webhook-cutover.json'


def command(*args, **kwargs):
    result = subprocess.run(args, capture_output=True, check=False, timeout=30, **kwargs)
    if result.returncode:
        raise RuntimeError('Required operator command failed; private output withheld')
    return result.stdout


def verify_reviewed_main(expected):
    if not expected or not re.fullmatch(r'[0-9a-f]{40}', expected):
        raise RuntimeError('Execution requires the full reviewed main commit in --expected-sha')
    if command('git', '-C', str(ROOT), 'status', '--porcelain=v1', '--untracked-files=all', '--ignore-submodules=none'):
        raise RuntimeError('Execution requires a clean checkout, including untracked files')
    head = command('git', '-C', str(ROOT), 'rev-parse', 'HEAD').decode().strip()
    remote = command('git', 'ls-remote', 'https://github.com/Stuhlmuller/homelab.git', 'refs/heads/main').decode().split()[0]
    if head != expected or remote != expected:
        raise RuntimeError('Checkout and remote main must match the reviewed execution commit')
    command('git', '-C', str(ROOT), 'cat-file', '-e', 'HEAD:scripts/policy-bot-webhook.py')


def credentials(config_file=None):
    if config_file:
        content = Path(config_file).read_bytes()
    else:
        secret = json.loads(command('kubectl', '--request-timeout=20s', '-n', 'automation',
                                    'get', 'secret', 'policy-bot-config', '-o', 'json'))
        content = base64.b64decode(secret['data']['policy-bot.yml'], validate=True)
    config = json.loads(command('yq', '-o=json', '.', input=content))
    app = config['github']['app']
    if not str(app['integration_id']).isdigit() or not app['private_key'].startswith('-----BEGIN '):
        raise RuntimeError('Policy Bot has no valid configured GitHub App identity')
    return str(app['integration_id']), app['private_key'].encode()


def app_jwt(app_id, private_key):
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b'=')
    if not 0 < len(private_key) <= 16384:
        raise RuntimeError('Unexpected GitHub App private-key size')
    now = int(time.time())
    message = b'.'.join(encode(json.dumps(value, separators=(',', ':')).encode()) for value in (
        {'alg': 'RS256', 'typ': 'JWT'}, {'iat': now - 60, 'exp': now + 540, 'iss': app_id}))
    # The key travels only through an inherited pipe, never argv, environment, or disk.
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, private_key)
        os.close(write_fd)
        write_fd = None
        signature = command('openssl', 'dgst', '-sha256', '-sign', f'/dev/fd/{read_fd}',
                            input=message, pass_fds=(read_fd,))
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
    return (message + b'.' + encode(signature)).decode()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def github_client(jwt):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    def request(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request('https://api.github.com' + path, data=data, method=method, headers={
            'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + jwt,
            'X-GitHub-Api-Version': '2026-03-10', 'Content-Type': 'application/json',
            'User-Agent': 'homelab-policy-bot-webhook',
        })
        try:
            with opener.open(req, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'GitHub request failed with HTTP {error.code}; response withheld') from None
    return request


def preflight_target():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for url, expected in ((URL, 400), (URL.removesuffix('/api/github/hook') + '/', 404)):
        try:
            with opener.open(urllib.request.Request(url, method='GET'), timeout=20) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
        if status != expected:
            raise RuntimeError('Funnel callback routing preflight failed; webhook configuration unchanged')


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('A timezone is required')
    return parsed.timestamp()


def read_receipt(path, url=URL):
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if (set(value) != {'url', 'started_at', 'previous_delivery_id'} or value['url'] != url
            or not isinstance(value['previous_delivery_id'], int) or value['previous_delivery_id'] < 0
            or timestamp(value['started_at']) > time.time()):
        raise RuntimeError('Cutover receipt is invalid; historical deliveries cannot establish acceptance')
    return value


def save_receipt(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
            temporary.chmod(0o600)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def new_cutover(api, url, delivery_path='/app/hook/deliveries'):
    deliveries = api('GET', delivery_path + '?per_page=10')
    if any(not isinstance(item.get('id'), int) or item['id'] <= 0 for item in deliveries):
        raise RuntimeError('Unexpected webhook delivery identifier')
    return {'url': url, 'started_at': datetime.fromtimestamp(time.time(), timezone.utc).isoformat(),
            'previous_delivery_id': max((item['id'] for item in deliveries), default=0)}


def delivery_status(api, url, cutover=None, delivery_path='/app/hook/deliveries'):
    deliveries = api('GET', delivery_path + '?per_page=10')
    for item in sorted(deliveries, key=lambda value: value.get('delivered_at', ''), reverse=True):
        if not isinstance(item.get('id'), int):
            raise RuntimeError('Unexpected webhook delivery identifier')
        delivery = api('GET', f"{delivery_path}/{item['id']}")
        if delivery.get('url') == url:
            status = delivery.get('status_code', 0)
            fresh = (cutover is not None and url == cutover['url']
                     and item['id'] > cutover['previous_delivery_id']
                     and timestamp(delivery['delivered_at']) >= timestamp(cutover['started_at']))
            print(f"Latest matching GitHub delivery: {item['id']}, HTTP {status}; fresh cutover delivery: {fresh}")
            return fresh and isinstance(status, int) and 200 <= status < 300
    print('No delivery to this callback found in the 10 most recent GitHub deliveries')
    return False


def reconcile(api, execute=False, require_delivery=False, receipt_path=None):
    receipt_path = RECEIPT if receipt_path is None else receipt_path
    cutover = read_receipt(receipt_path)
    previous = api('GET', CONFIG_PATH)
    if previous.get('url') not in (PREVIOUS_URL, URL):
        raise RuntimeError('Current webhook URL is outside the reviewed migration; refusing to change it')
    print('Current callback: ' + previous['url'])
    print('Declared callback: ' + URL)
    if execute:
        preflight_target()
        if previous['url'] != URL or cutover is None:
            cutover = new_cutover(api, URL)
        if previous['url'] != URL:
            api('PATCH', CONFIG_PATH, {'url': URL})
        current = api('GET', CONFIG_PATH)
        if current.get('url') != URL or any(current.get(key) != previous.get(key)
                                          for key in ('content_type', 'insecure_ssl', 'secret')):
            raise RuntimeError('Webhook readback did not preserve the declared URL and existing settings')
        save_receipt(receipt_path, cutover)
        print('Verified callback URL; existing secret and delivery settings preserved')
    else:
        print('Preview only; webhook configuration unchanged')
    delivered = delivery_status(api, URL if execute else previous['url'], cutover)
    if require_delivery and not delivered:
        raise RuntimeError('Successful delivery newer than this cutover is not yet verified; no event or redelivery was triggered')
    return delivered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-file', help='Existing file-backed policy-bot.yml; otherwise read only the Kubernetes Secret into memory')
    parser.add_argument('--execute', action='store_true', help='Apply only the fixed Funnel callback URL after exact-main checks')
    parser.add_argument('--expected-sha', help='Full reviewed main SHA required for execution')
    parser.add_argument('--require-delivery', action='store_true', help='Require a successful Funnel delivery newer than the saved cutover timestamp and delivery ID; never triggers events')
    args = parser.parse_args()
    if args.execute:
        verify_reviewed_main(args.expected_sha)
    app_id, key = credentials(args.config_file)
    api = github_client(app_jwt(app_id, key))
    if str(api('GET', '/app').get('id')) != app_id:
        raise RuntimeError('GitHub App identity does not match the configured Policy Bot identity')
    reconcile(api, args.execute, args.require_delivery)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        if isinstance(error, RuntimeError):
            raise SystemExit(str(error)) from None
        raise SystemExit('Webhook operation failed; credentials and private response output withheld') from None
