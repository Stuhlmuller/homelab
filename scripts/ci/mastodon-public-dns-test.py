#!/usr/bin/env python3
"""Reject DNS conflicts and foreign replacements before publishing one host."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('dns', ROOT / 'scripts/mastodon-public-dns.py')
dns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dns)
TUNNEL = '11111111-1111-4111-8111-111111111111'
# checkov:skip=CKV_SECRET_6: Inert fixture token used only for credential leak tests.
TOKEN = 'fixture-private-token'
DESIRED = {'type': 'CNAME', 'name': dns.HOST, 'content': TUNNEL + '.cfargotunnel.com',
           'proxied': True, 'ttl': 1, 'comment': dns.OWNER}


def exercise(records, count=None):
    writes = []

    def api(token, method, path, payload=None):
        assert token == TOKEN
        if path.startswith('/zones?'):
            return {'result': [{'name': dns.ZONE, 'status': 'active', 'id': 'a' * 32}]}
        if method == 'GET':
            assert path.endswith('?name=' + dns.HOST + '&per_page=100')
            return {'result': records, 'result_info': {'total_count': len(records) if count is None else count}}
        assert payload == DESIRED
        assert path.startswith('/zones/' + 'a' * 32 + '/dns_records')
        writes.append((method, path))
        return {'result': DESIRED}

    with patch.object(dns, 'api', side_effect=api), patch.object(dns.credential, 'validate_context'):
        try:
            dns.reconcile(TOKEN, TUNNEL)
        except RuntimeError:
            assert not writes
            return False, writes
    return True, writes


assert exercise([])[1] == [('POST', '/zones/' + 'a' * 32 + '/dns_records')]
assert exercise([DESIRED])[1] == []
owned = {**DESIRED, 'id': 'b' * 32, 'proxied': False}
assert exercise([owned])[1] == [('PUT', '/zones/' + 'a' * 32 + '/dns_records/' + 'b' * 32)]
for records, count in [
    ([{**owned, 'type': 'A'}], None),
    ([{**owned, 'comment': 'foreign'}], None),
    ([{**owned, 'name': 'stinkyboi.com'}], None),
    ([owned, owned], None),
    ([owned], 2),
    ([], False),
]:
    assert exercise(records, count)[0] is False
sha = 'a' * 40
apps = [{'metadata': {'name': name}, 'status': {'sync': {'status': 'Synced', 'revisions': [sha]},
        'health': {'status': 'Healthy'}}} for name in ['mastodon', 'octelium-public']]
with patch.dict(os.environ, {'GITHUB_SHA': sha}), patch.object(dns.credential, 'command', return_value=json.dumps({'items': apps})):
    dns.ready()
for invalid in [apps[:1], apps + [apps[0]], [{**app, 'status': {}} for app in apps]]:
    with patch.dict(os.environ, {'GITHUB_SHA': sha}), patch.object(dns.credential, 'command', return_value=json.dumps({'items': invalid})):
        try:
            dns.ready()
            raise AssertionError('Unready rollout accepted')
        except RuntimeError:
            pass
with patch.object(dns.credential, 'validate_context', side_effect=RuntimeError(TOKEN)), \
        contextlib.redirect_stderr(io.StringIO()) as output:
    assert dns.main() == 1
    assert TOKEN not in output.getvalue()
try:
    dns.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://invalid')
    raise AssertionError('Redirect accepted')
except RuntimeError:
    pass
print('Mastodon DNS: create, idempotence, owned update, conflict refusal, and private-output checks passed')
