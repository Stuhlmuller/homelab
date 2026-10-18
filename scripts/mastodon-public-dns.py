#!/usr/bin/env python3
"""Publish only Mastodon's reviewed Cloudflare Tunnel DNS record from CI."""
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
HOST = 'mastodon.stinkyboi.com'
ZONE = 'stinkyboi.com'
OWNER = 'homelab-mastodon-public'
TOKEN_PARAMETER = '/homelab/cert-manager/cloudflare-api-token'
TUNNEL_PARAMETER = '/homelab/octelium/cloudflare-tunnel-id'
spec = importlib.util.spec_from_file_location('credential', ROOT / 'scripts/mastodon-smtp-credential.py')
credential = importlib.util.module_from_spec(spec)
spec.loader.exec_module(credential)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Redirect rejected')


def api(token, method, path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request('https://api.cloudflare.com/client/v4' + path,
                                    data=body, method=method,
                                    headers={'Authorization': 'Bearer ' + token,
                                             'Content-Type': 'application/json'})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        data = json.loads(response.read(1048576))
    if data.get('success') is not True:
        raise RuntimeError('Cloudflare request failed')
    return data


def parameter(name):
    data = json.loads(credential.command(['aws', 'ssm', 'get-parameter', '--region', 'us-west-2',
                                         '--name', name, '--with-decryption', '--output', 'json']))['Parameter']
    if data.get('Name') != name or data.get('Type') != 'SecureString':
        raise RuntimeError('Unexpected parameter')
    value = data['Value']
    if not value or value == 'REPLACE_ME':
        raise RuntimeError('Missing credential')
    return value


def ready():
    sha = os.environ['GITHUB_SHA']
    data = json.loads(credential.command(['kubectl', '-n', 'argocd', 'get', 'applications',
                                         'mastodon', 'octelium-public', '-o', 'json']))
    if len(data.get('items', [])) != 2 or {item['metadata']['name'] for item in data['items']} != {'mastodon', 'octelium-public'}:
        raise RuntimeError('Applications missing')
    for item in data['items']:
        status = item.get('status', {})
        sync = status.get('sync', {})
        revisions = sync.get('revisions', [sync.get('revision')])
        if (sync.get('status') != 'Synced' or status.get('health', {}).get('status') != 'Healthy'
                or revisions != [sha]):
            raise RuntimeError('Reviewed rollout not ready')


def reconcile(token, tunnel):
    tunnel = str(uuid.UUID(tunnel))
    zones = api(token, 'GET', '/zones?name=' + ZONE)['result']
    if len(zones) != 1 or zones[0].get('name') != ZONE or zones[0].get('status') != 'active':
        raise RuntimeError('Expected active zone')
    zone = zones[0]['id']
    if not re.fullmatch('[a-f0-9]{32}', zone):
        raise RuntimeError('Invalid zone identity')
    path = '/zones/' + zone + '/dns_records'
    data = api(token, 'GET', path + '?name=' + urllib.parse.quote(HOST) + '&per_page=100')
    records = data['result']
    count = data.get('result_info', {}).get('total_count')
    if not isinstance(records, list) or type(count) is not int or count != len(records) or len(records) > 1:
        raise RuntimeError('Incomplete or conflicting DNS records')
    desired = {'type': 'CNAME', 'name': HOST, 'content': tunnel + '.cfargotunnel.com',
               'proxied': True, 'ttl': 1, 'comment': OWNER}
    if records:
        record = records[0]
        if record.get('name') != HOST or record.get('type') != 'CNAME':
            raise RuntimeError('Conflicting record type')
        if all(record.get(key) == value for key, value in desired.items()):
            return
        if record.get('comment') != OWNER or not re.fullmatch('[a-f0-9]{32}', record.get('id', '')):
            raise RuntimeError('Refusing foreign record replacement')
        path += '/' + record['id']
        method = 'PUT'
    else:
        method = 'POST'
    credential.validate_context()
    record = api(token, method, path, desired)['result']
    if not all(record.get(key) == value for key, value in desired.items()):
        raise RuntimeError('Uncertain DNS write')


def main():
    try:
        if len(sys.argv) != 1:
            raise RuntimeError('No inputs supported')
        credential.validate_context()
        ready()
        reconcile(parameter(TOKEN_PARAMETER), parameter(TUNNEL_PARAMETER))
        print('Mastodon public DNS reconciled; verify browser access and federation before acceptance.')
        return 0
    except Exception:
        print('Mastodon DNS publication failed; private details withheld.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
