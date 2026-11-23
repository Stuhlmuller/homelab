#!/usr/bin/env python3
"""Reject DNS conflicts and foreign replacements before publishing one host."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('dns', ROOT / 'scripts/mastodon-public-dns.py')
dns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dns)
TUNNEL = '11111111-1111-4111-8111-111111111111'
# checkov:skip=CKV_SECRET_6: Inert fixture token used only for credential leak tests.
TOKEN = 'fixture-private-token'


def exercise(site, desired, records, count=None):
    writes = []

    def api(token, method, path, payload=None):
        assert token == TOKEN
        if path.startswith('/zones?'):
            return {'result': [{'name': dns.ZONE, 'status': 'active', 'id': 'a' * 32}]}
        if method == 'GET':
            assert path.endswith('?name=' + desired['name'] + '&per_page=100')
            return {'result': records, 'result_info': {'total_count': len(records) if count is None else count}}
        assert payload == desired
        assert path.startswith('/zones/' + 'a' * 32 + '/dns_records')
        writes.append((method, path))
        return {'result': desired}

    with patch.object(dns, 'api', side_effect=api), patch.object(dns.credential, 'validate_context'):
        try:
            dns.reconcile(TOKEN, TUNNEL, site, 'a' * 40)
        except RuntimeError:
            assert not writes
            return False, writes
    return True, writes


for site, other in [('mastodon', 'openwiki'), ('openwiki', 'mastodon'), ('bazel-cache', 'mastodon')]:
    desired = {'type': 'CNAME', 'name': f'{site}.stinkyboi.com', 'content': TUNNEL + '.cfargotunnel.com',
               'proxied': True, 'ttl': 1, 'comment': f'homelab-{site}-public'}
    assert exercise(site, desired, [])[1] == [('POST', '/zones/' + 'a' * 32 + '/dns_records')]
    assert exercise(site, desired, [desired])[1] == []
    owned = {**desired, 'id': 'b' * 32, 'proxied': False}
    assert exercise(site, desired, [owned])[1] == [('PUT', '/zones/' + 'a' * 32 + '/dns_records/' + 'b' * 32)]
    for records, count in [
        ([{**owned, 'type': 'A'}], None),
        ([{**owned, 'comment': f'homelab-{other}-public'}], None),
        ([{**owned, 'name': 'stinkyboi.com'}], None),
        ([owned, owned], None),
        ([owned], 2),
        ([], False),
    ]:
        assert exercise(site, desired, records, count)[0] is False

    sha = 'a' * 40
    expected_apps = ['octelium-public'] if site == 'bazel-cache' else [site, 'octelium-public']
    apps = [{'metadata': {'name': name}, 'status': {'sync': {'status': 'Synced', 'revisions': [sha]},
            'health': {'status': 'Healthy'}}} for name in expected_apps]
    output = {'kind': 'Application', **apps[0]} if len(apps) == 1 else {'items': apps}
    with patch.dict(os.environ, {'GITHUB_SHA': sha}), patch.object(
        dns.credential, 'command', return_value=json.dumps(output)
    ) as command:
        dns.ready(site, sha)
        command.assert_called_once_with(['kubectl', '-n', 'argocd', 'get', 'applications',
                                         *expected_apps, '-o', 'json'])
    for invalid in [apps[1:], apps + [apps[0]], [*apps[1:], {**apps[0], 'metadata': {'name': other}}],
                    [{**app, 'status': {}} for app in apps]]:
        with patch.dict(os.environ, {'GITHUB_SHA': sha}), patch.object(
            dns.credential, 'command', return_value=json.dumps({'items': invalid})
        ):
            try:
                dns.ready(site, sha)
                raise AssertionError('Unready rollout accepted')
            except RuntimeError:
                pass
    with patch.dict(os.environ, {'GITHUB_SHA': 'b' * 40}), patch.object(
        dns.credential, 'command', return_value=json.dumps({'items': apps})
    ), patch.object(dns.credential, 'validate_context'), patch.object(dns, 'parameter') as parameter, \
            contextlib.redirect_stderr(io.StringIO()):
        assert dns.main([site]) == 1
        parameter.assert_not_called()
    with patch.dict(os.environ, {'GITHUB_SHA': 'b' * 40, 'VALIDATED_SHA': sha}), patch.object(
        dns.credential, 'command', return_value=json.dumps({'items': apps})
    ), patch.object(dns.credential, 'validate_context') as context, patch.object(
        dns, 'parameter', side_effect=[TOKEN, TUNNEL]
    ), patch.object(dns, 'reconcile') as reconcile, contextlib.redirect_stdout(io.StringIO()):
        assert dns.main([site]) == 0
        context.assert_called_once_with(sha)
        reconcile.assert_called_once_with(TOKEN, TUNNEL, site, sha)

validated = 'a' * 40
dispatch = 'b' * 40
identity = {
    'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'Stuhlmuller/homelab',
    'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
    'GITHUB_SHA': dispatch, 'VALIDATED_SHA': validated,
}
with patch.dict(os.environ, identity, clear=True), patch.object(
    dns.credential, 'command', side_effect=[validated, f'{validated}\trefs/heads/main']
):
    dns.credential.validate_context(validated)
with patch.dict(os.environ, identity, clear=True), patch.object(
    dns.credential, 'command', side_effect=[validated, f'{dispatch}\trefs/heads/main']
), patch.object(dns, 'parameter') as parameter, contextlib.redirect_stderr(io.StringIO()):
    assert dns.main(['openwiki']) == 1
    parameter.assert_not_called()
with patch.dict(os.environ, identity, clear=True), patch.object(
    dns.credential, 'command', return_value=dispatch
):
    with TestCase().assertRaisesRegex(RuntimeError, 'Checkout mismatch'):
        dns.credential.validate_context(validated)

with patch.object(dns.credential, 'validate_context') as context, contextlib.redirect_stderr(io.StringIO()):
    assert dns.main(['arbitrary.stinkyboi.com']) == 1
    context.assert_not_called()
with patch.object(dns.credential, 'validate_context', side_effect=RuntimeError(TOKEN)), \
        contextlib.redirect_stderr(io.StringIO()) as output:
    assert dns.main([]) == 1
    assert TOKEN not in output.getvalue()
try:
    dns.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://invalid')
    raise AssertionError('Redirect accepted')
except RuntimeError:
    pass
print('Public Tunnel DNS: create, idempotence, owned update, conflict refusal, and rollout checks passed')
