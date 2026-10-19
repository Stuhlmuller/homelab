#!/usr/bin/env python3
"""Exercise mesh cutover guards and DNS reconciliation without network access."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import parse_qs
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check", ROOT / "scripts/tailscale-private-dns-check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class Readiness(unittest.TestCase):
    def test_fixed_inventory_covers_apps_and_only_intended_legacy_names(self):
        value = check.inventory()
        apps = 'affine argocd bazarr compass deluge dispatcharr fleet grafana harbor kiali langfuse litellm multica n8n nofx openclaw policy-bot prowlarr radarr sonarr'.split()
        self.assertEqual(set(value['hostnames']), {f'{app}.stinkyboi.com' for app in apps} | {
            'stinkyboi.com', 'cordium.stinkyboi.com', '*.cordium.stinkyboi.com', 'console.stinkyboi.com',
            'octelium.stinkyboi.com', 'octelium-api.stinkyboi.com', 'portal.stinkyboi.com',
            'console.oce.stinkyboi.com', '*.agents.oce.stinkyboi.com'})
        self.assertEqual(set(value['retired_hostnames']), {f'{name}.stinkyboi.com' for name in (
            'octelium-transport', 'kubernetes-api-ci', 'n8n-webhook', 'policy-bot-hook')})
        self.assertEqual(check.retirement_names(value), value['hostnames'][1:27])
        self.assertEqual(len(check.retirement_names(value)), 26)
        self.assertNotIn('stinkyboi.com', check.retirement_names(value))
        self.assertFalse(set(check.retirement_names(value)) & set(value['retired_hostnames']))
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory)/'inventory.json'
            changed.write_text(json.dumps({**value, 'hostnames': value['hostnames'][:-1]}))
            with patch.object(check, 'INVENTORY', changed), self.assertRaisesRegex(RuntimeError, 'fixed 27-name'):
                check.inventory()

    def exercise(self, failure=None, dualstack_peer=False):
        service = {'metadata': {'annotations': {'tailscale.com/hostname': 'homelab-ingress'}},
                   'spec': {'type': 'LoadBalancer', 'loadBalancerClass': 'tailscale',
                            'ports': [{'port': 443, 'targetPort': 8443}]},
                   'status': {'loadBalancer': {'ingress': [{'hostname': check.TARGET}, {'ip': '100.100.100.1'}]}}}
        config = {'data': {name: (ROOT/'clusters/homelab/apps/traefik'/name).read_text()
                           for name in ('routes.yaml', 'tls.yaml')}}
        if failure == 'hostname':
            service['status']['loadBalancer']['ingress'][0]['hostname'] = 'unexpected.tail67beb.ts.net'
        if failure == 'unpublished':
            service['status']['loadBalancer']['ingress'].pop()
        if failure == 'address':
            service['status']['loadBalancer']['ingress'][1]['ip'] = '8.8.8.8'
        if failure == 'config':
            config['data']['routes.yaml'] = 'old routes'
        commands = []

        def run(*command):
            commands.append(command)
            if command[0] == 'kubectl':
                return json.dumps(service if 'service' in command else config)
            if command[-2:] == ('status', '--json'):
                return json.dumps({'BackendState':'Running', 'Self':{'Online':True},
                    'CurrentTailnet':{'MagicDNSSuffix':'tail67beb.ts.net'},
                    'Peer':{'ingress':{'DNSName':check.TARGET+'.', 'Online':True,
                        'TailscaleIPs':['100.100.100.1' if failure != 'peer' else '100.100.100.2']
                                       + (['fd7a:115c:a1e0::1'] if dualstack_peer else [])}}})
            host = command[-1].split('/')[2]
            if host == 'octelium-api.stinkyboi.com':
                protocol = next(value.split(': ', 1)[1] for value in command if value.startswith('content-type: '))
                body = b''
                status = f'grpc-status: {0 if failure == "grpc" else 16}\n'
                if failure == 'duplicate-status':
                    status += 'grpc-status: 0\n'
                if failure == 'native-proto' and protocol == 'application/grpc':
                    protocol += '+proto'
                if failure == 'browser-body' and protocol == 'application/grpc-web+proto':
                    trailer = b'grpc-status: 16\r\n'
                    body = b'\x80' + len(trailer).to_bytes(4, 'big') + trailer
                    status = ''
                if failure == 'parameters':
                    protocol += '; charset=utf-8'
                Path(command[command.index('--output') + 1]).write_bytes(body)
                return f'HTTP/2 200\ncontent-type: {protocol}\n{status}\n200'
            if host == 'harbor.stinkyboi.com':
                realm = 'wrong.example' if failure == 'realm' else host
                return f'HTTP/2 401\nwww-authenticate: Bearer realm="https://{realm}/service/token"\n\n401'
            return 'HTTP/2 503\n\n503' if failure == 'backend' else 'HTTP/2 200\n\n200'

        with patch.object(check, 'run', side_effect=run), contextlib.redirect_stderr(io.StringIO()):
            addresses = check.mesh_addresses()
            if dualstack_peer:
                self.assertEqual(addresses, {'A':['100.100.100.1'], 'AAAA':[]})
            check.declared_routes()
            for address in addresses['A'] + addresses['AAAA']:
                check.routes(check.inventory(), address)
        return commands

    def test_readiness_uses_real_host_tls_and_rejects_wrong_mesh_or_upstreams(self):
        commands = self.exercise()
        self.assertEqual(commands[0], ('kubectl', '-n', 'traefik', 'get', 'service', 'traefik-private', '-o', 'json'))
        probes = [command for command in commands if command[0] == 'curl']
        self.assertEqual(len(probes), 30)
        self.assertTrue(all('--connect-to' in command and '--disable' in command and '--insecure' not in command
                            for command in probes))
        for failure in ('hostname', 'unpublished', 'config', 'grpc', 'realm', 'backend', 'address', 'peer'):
            with self.subTest(failure=failure), self.assertRaises(RuntimeError):
                self.exercise(failure)

    def test_ipv4_service_does_not_publish_dualstack_peers_unsupported_ipv6(self):
        commands = self.exercise(dualstack_peer=True)
        probes = [command for command in commands if command[0] == 'curl']
        self.assertEqual(len(probes), 30)
        self.assertTrue(all(command[command.index('--connect-to') + 1].endswith(':100.100.100.1:443')
                            for command in probes))

    def test_api_parser_accepts_protocol_variants_and_rejects_conflicting_status(self):
        for response in ('native-proto', 'browser-body', 'parameters'):
            with self.subTest(response=response):
                self.exercise(response)
        with self.assertRaisesRegex(RuntimeError, 'authentication probes'):
            self.exercise('duplicate-status')

    def test_execute_checks_reviewed_main_before_readiness(self):
        with patch.object(sys, 'argv', ['check', '--retire-private', '--execute', '--expected-sha', 'a'*40,
                                        '--evidence', '/private/tmp/cutover-evidence.json']), \
                patch.object(check, 'verify_main', side_effect=RuntimeError('main differs')) as verify, \
                patch.object(check, 'mesh_addresses') as readiness:
            with self.assertRaisesRegex(RuntimeError, 'main differs'):
                check.main()
            verify.assert_called_once_with('a'*40)
            readiness.assert_not_called()

    def test_affine_500_502_and_503_require_explicit_source_and_live_suspension(self):
        source = {'kind':'Deployment', 'metadata':{'name':'affine'}, 'spec':{'replicas':0}}
        live = {'metadata':{'name':'affine','namespace':'affine'},'spec':{'replicas':0},'status':{'replicas':0}}
        cases = [(source, live, True), (source, {key:value for key,value in live.items() if key != 'status'}, True)]
        for target, fields in ((source, {'kind':['StatefulSet',None], 'metadata':[{'name':'other'},{}],
                                        'spec':[{'replicas':value} for value in (1,None,'0',False)]}),
                               (live, {'metadata':[{'name':'other','namespace':'affine'}, {'name':'affine','namespace':'other'},{}],
                                       'spec':[{'replicas':value} for value in (1,None,'0',False)],
                                       'status':[{'replicas':1}, {'replicas':'0'}]})):
            for field, values in fields.items():
                for value in values:
                    changed = dict(target, **{field:value})
                    cases.append((changed if target is source else source, changed if target is live else live, False))
        for status in (500, 502, 503):
            for desired, actual, accepted in cases:
                with self.subTest(status=status, desired=desired, actual=actual), patch.object(check, 'run',
                        side_effect=[json.dumps(desired), json.dumps(actual)]), patch.object(check, 'probe', return_value=(status, [])), \
                        contextlib.redirect_stderr(io.StringIO()):
                    if accepted:
                        check.routes({'hostnames':['affine.stinkyboi.com']}, '100.100.100.1')
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'readiness failed'):
                            check.routes({'hostnames':['affine.stinkyboi.com']}, '100.100.100.1')
            for responses in ([RuntimeError('source read failed')], [json.dumps(source), RuntimeError('live read failed')]):
                with self.subTest(status=status, failure=responses), patch.object(check, 'run', side_effect=responses), \
                        patch.object(check, 'probe', return_value=(status, [])):
                    with self.assertRaisesRegex(RuntimeError, 'read failed'):
                        check.routes({'hostnames':['affine.stinkyboi.com']})

    def test_suspension_exception_does_not_allow_other_apps_or_other_5xx(self):
        for host in ('affine', 'openclaw', 'n8n', 'fleet', 'harbor'):
            for status in (500, 502, 503, 504):
                if host == 'affine' and status in (500, 502, 503):
                    continue
                with self.subTest(host=host, status=status), patch.object(check, 'probe', return_value=(status, [])), \
                        patch.object(check, 'affine_suspended') as affine:
                    with self.assertRaisesRegex(RuntimeError, 'readiness failed'):
                        check.routes({'hostnames':[f'{host}.stinkyboi.com']})
                    affine.assert_not_called()

    def test_private_preflight_requires_direct_and_normal_client_dns_without_connection_override(self):
        commands = []
        addresses = {'A':['100.100.100.1'], 'AAAA':[]}
        def run(*command):
            commands.append(command)
            return 'HTTP/2 200\n\n200'
        value = {'hostnames':['stinkyboi.com', '*.cordium.stinkyboi.com'], 'retired_hostnames':[]}
        with patch.object(check, 'run', side_effect=run), patch.object(check.socket, 'getaddrinfo',
                return_value=[(None,None,None,None,('100.100.100.1',443))]), contextlib.redirect_stderr(io.StringIO()):
            check.verify_private_dns(value, addresses, '100.100.100.2')
        self.assertEqual(commands[0][-2:], ('--server', '100.100.100.2'))
        probes = [command for command in commands if command[0] == 'curl']
        self.assertEqual(len(probes), 2)
        self.assertNotIn('--connect-to', probes[0])
        with patch.object(check, 'run', side_effect=run), patch.object(check.socket, 'getaddrinfo',
                return_value=[(None,None,None,None,('104.16.1.2',443))]), self.assertRaisesRegex(RuntimeError, 'does not match'):
            check.verify_private_dns(value, addresses, '100.100.100.2')


class RetirementEvidence(unittest.TestCase):
    def test_authoritative_answer_parser_requires_aa_and_valid_owner(self):
        header = ';; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n;; flags: qr aa; QUERY: 1, ANSWER: 1, AUTHORITY: 0\n'
        answer = ';; ANSWER SECTION:\nportal.stinkyboi.com. 60 IN A 100.99.16.74\n'
        with patch.object(check, 'run', return_value=header + answer):
            self.assertEqual(check.public_answers('mock.ns.cloudflare.com.', 'portal.stinkyboi.com', 'A'),
                             [('portal.stinkyboi.com', 'A', '100.99.16.74', 60)])
            self.assertEqual(check.answers('mock.ns.cloudflare.com.', 'portal.stinkyboi.com', 'A'),
                             [('A', '100.99.16.74', 60)])
        nodata = header.replace('ANSWER: 1', 'ANSWER: 0')
        with patch.object(check, 'run', return_value=nodata):
            self.assertEqual(check.answers('mock.ns.cloudflare.com.', 'portal.stinkyboi.com', 'A'), [])
        for response in (header.replace('qr aa', 'qr') + answer,
                         header.replace('qr aa', 'qr aa tc') + answer,
                         header.replace('NOERROR', 'SERVFAIL') + answer,
                         header + answer.replace('portal.stinkyboi.com.', 'wrong.stinkyboi.com.'),
                         header + answer.replace('60 IN A', 'invalid'), header,
                         nodata + answer, ''):
            with self.subTest(response=response), patch.object(check, 'run', return_value=response), \
                    self.assertRaises(RuntimeError):
                check.answers('mock.ns.cloudflare.com.', 'portal.stinkyboi.com', 'A')

    def test_previous_ttl_accepts_authoritative_nodata_and_rejects_failed_dns(self):
        nodata = ';; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n;; flags: qr aa; QUERY: 1, ANSWER: 0, AUTHORITY: 1\n'
        with patch.object(check, 'authoritative_servers', return_value=['mock.ns.cloudflare.com.']), \
                patch.object(check, 'run', return_value=nodata):
            self.assertEqual(check.previous_ttl(check.inventory()), 0)
        for response in ('', nodata.replace('NOERROR', 'SERVFAIL'), nodata.replace('qr aa', 'qr')):
            with self.subTest(response=response), patch.object(check, 'authoritative_servers',
                    return_value=['mock.ns.cloudflare.com.']), patch.object(check, 'run', return_value=response), \
                    self.assertRaises(RuntimeError):
                check.previous_ttl(check.inventory())

    def test_cloudflare_zone_nameservers_match_parent_delegation(self):
        referral = (';; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n'
                    ';; flags: qr; QUERY: 1, ANSWER: 0, AUTHORITY: 2\n'
                    ';; AUTHORITY SECTION:\n'
                    'stinkyboi.com. 172800 IN NS ursula.ns.cloudflare.com.\n'
                    'stinkyboi.com. 172800 IN NS armando.ns.cloudflare.com.\n')
        with patch.object(check, 'run', return_value=referral):
            self.assertEqual(check.authoritative_servers(),
                             ['armando.ns.cloudflare.com.', 'ursula.ns.cloudflare.com.'])
            check.verify_zone_nameservers(['URSULA.ns.cloudflare.com', 'armando.ns.cloudflare.com.'])
            for names in ([], ['ursula.ns.cloudflare.com'],
                          ['ursula.ns.cloudflare.com', 'wrong.ns.cloudflare.com'],
                          ['ursula.ns.cloudflare.com', 'ursula.ns.cloudflare.com']):
                with self.subTest(names=names), self.assertRaises(RuntimeError):
                    check.verify_zone_nameservers(names)
        for response in ('', referral.replace('NOERROR', 'SERVFAIL'),
                         referral.replace('flags: qr;', 'flags: qr tc;'),
                         referral.replace('AUTHORITY: 2', 'AUTHORITY: 3'),
                         referral.replace('stinkyboi.com. 172800', 'other.com. 172800')):
            with self.subTest(response=response), patch.object(check, 'run', return_value=response), \
                    self.assertRaises(RuntimeError):
                check.authoritative_servers()

    def evidence(self):
        value = check.inventory()
        names = check.retirement_names(value)
        return {
            'reviewed_main_sha': 'a' * 40,
            'resolver_ip': '100.100.100.2',
            'owner_tailnet_dns_confirmed': True,
            'normal_client_dns_confirmed': True,
            'critical_paths_confirmed': {
                'fleet_setup_denied': True, 'harbor_node_pulls': True,
                'native_api': True, 'cordium_reconnect': True, 'public_callbacks': True,
            },
            'off_tailnet': {name: 'migrated' for name in names},
            'previous_ttl_seconds': 300,
            'checked_names': names,
            'baseline_records': [
                {'id': f'record-{index}', 'name': host, 'type': 'A',
                 'content': '100.100.100.1', 'proxied': False, 'ttl': 60}
                for index, host in enumerate(names)
            ],
        }

    def test_evidence_is_exact_and_requires_all_cutover_decisions(self):
        value = check.inventory()
        evidence = self.evidence()
        self.assertEqual(check.validate_retirement_evidence(evidence, value, 'a' * 40),
                         '100.100.100.2')
        for key, replacement in (
            ('reviewed_main_sha', 'b' * 40), ('owner_tailnet_dns_confirmed', False),
            ('normal_client_dns_confirmed', False), ('resolver_ip', '8.8.8.8'),
            ('previous_ttl_seconds', 0),
            ('critical_paths_confirmed', {'fleet_setup_denied': True}),
            ('off_tailnet', {'*.cordium.stinkyboi.com': 'migrated'}),
            ('off_tailnet', {**evidence['off_tailnet'], 'stinkyboi.com': 'accepted_loss'}),
            ('checked_names', value['hostnames']),
            ('checked_names', check.retirement_names(value)[:-1]),
        ):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                check.validate_retirement_evidence({**evidence, key: replacement}, value, 'a' * 40)
        for record in ({**evidence['baseline_records'][0], 'name': 'mastodon.stinkyboi.com'},
                       {**evidence['baseline_records'][0], 'name': 'stinkyboi.com'},
                       {**evidence['baseline_records'][0], 'type': 'TXT'}):
            with self.subTest(record=record), self.assertRaises(RuntimeError):
                check.validate_retirement_evidence(
                    {**evidence, 'baseline_records': [record] + evidence['baseline_records'][1:]},
                    value, 'a' * 40)
        self.assertEqual(check.validate_retirement_evidence(
            {**evidence, 'baseline_records': evidence['baseline_records'][:-1]}, value, 'a' * 40),
            '100.100.100.2')
        self.assertEqual(check.validate_retirement_evidence(
            {**evidence, 'baseline_records': [], 'previous_ttl_seconds': 0}, value, 'a' * 40),
            '100.100.100.2')
        with self.assertRaisesRegex(RuntimeError, 'measured old TTL'):
            check.validate_retirement_evidence({**evidence, 'previous_ttl_seconds': 0}, value, 'a' * 40)

    def test_execute_rejects_a_public_ttl_above_the_saved_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_file = Path(directory)/'evidence.json'
            evidence_file.write_text(json.dumps(self.evidence()))
            with patch.object(sys, 'argv', ['check', '--retire-private', '--execute',
                                            '--expected-sha', 'a'*40, '--evidence', str(evidence_file)]), \
                    patch.object(check, 'verify_main'), patch.object(check, 'previous_ttl', return_value=301), \
                    patch.object(check, 'mesh_addresses') as mesh:
                with self.assertRaisesRegex(RuntimeError, 'exceeds the saved baseline'):
                    check.main()
                mesh.assert_not_called()


class DNS(unittest.TestCase):
    def exercise(self, execute=False, failure=None, already=False, retry=False,
                 missing=False, empty_baseline=False):
        with tempfile.TemporaryDirectory(prefix='private-dns-test-') as directory:
            base = Path(directory)
            repo = base/'repo'
            script = repo/'scripts/tailscale-private-dns.sh'
            script.parent.mkdir(parents=True)
            shutil.copyfile(ROOT/'scripts/tailscale-private-dns.sh', script)
            (repo/'scripts/config').mkdir()
            shutil.copyfile(ROOT/'scripts/config/tailscale-private-dns.json', repo/'scripts/config/tailscale-private-dns.json')
            inventory = check.inventory()
            initial = {}
            for index, host in enumerate(inventory['hostnames']):
                initial[host] = [] if (empty_baseline and host != 'stinkyboi.com') or (missing and index == 26) else [
                    {'id': f'a-{index}', 'name': host, 'type': 'A',
                     'content': '100.100.100.1', 'proxied': False, 'ttl': 60}]
            if not empty_baseline:
                for kind, ident, content in (('AAAA', 'v6', 'fd7a:115c:a1e0::1'),
                                             ('CNAME', 'alias', 'old.cfargotunnel.com')):
                    host = inventory['hostnames'][1 if kind == 'AAAA' else 2]
                    initial[host].append({'id': ident, 'name': host, 'type': kind,
                                          'content': content, 'proxied': kind == 'CNAME', 'ttl': 60})
            initial['stinkyboi.com'].extend([
                {'id': 'keep-txt', 'name': 'stinkyboi.com', 'type': 'TXT', 'content': 'dummy-private-value'},
                {'id': 'keep-mx', 'name': 'stinkyboi.com', 'type': 'MX', 'content': 'mail.example'},
                {'id': 'keep-caa', 'name': 'stinkyboi.com', 'type': 'CAA', 'content': 'issue letsencrypt.org'},
                {'id': 'keep-ns', 'name': 'stinkyboi.com', 'type': 'NS', 'content': 'a.ns.cloudflare.com'},
                {'id': 'keep-soa', 'name': 'stinkyboi.com', 'type': 'SOA', 'content': 'a.ns.cloudflare.com'},
            ])
            initial['argocd.stinkyboi.com'].append(
                {'id': 'keep-target-txt', 'name': 'argocd.stinkyboi.com', 'type': 'TXT', 'content': 'retain'})
            for index, host in enumerate(inventory['retired_hostnames']):
                initial[host] = [{'id': f'legacy-{index}', 'name': host, 'type': 'CNAME',
                                  'content': 'old.cfargotunnel.com', 'proxied': True, 'ttl': 60}]
            initial['mastodon.stinkyboi.com'] = [
                {'id': 'public', 'name': 'mastodon.stinkyboi.com', 'type': 'A', 'content': '192.0.2.10'}]
            for index in range(110):
                host = f'unrelated-{index}.stinkyboi.com'
                initial[host] = [{'id': f'unrelated-{index}', 'name': host, 'type': 'A', 'content': '192.0.2.10'}]
            if failure in ('wildcard', 'cname'):
                initial['*.stinkyboi.com'] = [
                    {'id': 'public-wildcard', 'name': '*.stinkyboi.com',
                     'type': 'CNAME' if failure == 'cname' else 'A', 'content': 'public.example'}]
            if failure == 'delegation':
                initial['cordium.stinkyboi.com'].append(
                    {'id': 'child-ns', 'name': 'cordium.stinkyboi.com', 'type': 'NS', 'content': 'ns.child.example'})
            if failure == 'wildcard-delegation':
                initial['*.stinkyboi.com'] = [
                    {'id': 'wildcard-ns', 'name': '*.stinkyboi.com',
                     'type': 'NS', 'content': 'ns.child.example'}]
            if failure == 'child':
                initial['dns-preflight.cordium.stinkyboi.com'] = [
                    {'id': 'public-child', 'name': 'dns-preflight.cordium.stinkyboi.com',
                     'type': 'A', 'content': '192.0.2.11'}]
            before = json.loads(json.dumps(initial))
            evidence = RetirementEvidence().evidence()
            evidence['baseline_records'] = [
                record for host in check.retirement_names(inventory) for record in initial[host]
                if record['type'] in ('A', 'AAAA', 'CNAME')]
            if empty_baseline:
                evidence['previous_ttl_seconds'] = 0
            evidence_file = base/'cutover-evidence.json'
            evidence_file.write_text(json.dumps(evidence))
            if already:
                for host in check.retirement_names(inventory):
                    initial[host] = [record for record in initial[host]
                                     if record['type'] not in ('A', 'AAAA', 'CNAME')]
            if failure == 'drift':
                initial['sonarr.stinkyboi.com'][0]['content'] = '100.100.100.9'
            state = base/'state.json'
            state.write_text(json.dumps(initial))
            calls = base/'calls.jsonl'
            calls.write_text('')
            binary = base/'bin'
            binary.mkdir()
            fake = r'''
import importlib.util, json, sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs
BASE = Path(BASE_VALUE)
args = sys.argv[1:]
name = Path(sys.argv[0]).name
failure = FAILURE_VALUE
if name == 'git':
    print('a' * 40)
elif name == 'aws':
    print('fake-secret-must-not-leak')
elif name == 'python3':
    with (BASE/'calls.jsonl').open('a') as stream: stream.write(json.dumps(['preflight', args]) + '\n')
    if failure in ('ttl-servfail', 'ttl-nonauthoritative') and ('--execute' in args or '--baseline-ttl' in args):
        spec = importlib.util.spec_from_file_location('check', SOURCE_VALUE)
        check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(check)
        reply = (';; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n'
                 ';; flags: qr aa; QUERY: 1, ANSWER: 0, AUTHORITY: 0\n')
        reply = reply.replace('NOERROR', 'SERVFAIL') if failure == 'ttl-servfail' else reply.replace('qr aa', 'qr')
        check.verify_main = lambda expected: None
        check.authoritative_servers = lambda: ['mock.ns.cloudflare.com.']
        check.run = lambda *command: reply
        sys.argv = ['check'] + args[args.index('--retire-private'):]
        try:
            check.main()
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            sys.exit(1)
        sys.exit(2)
    if '--baseline-ttl' in args:
        print('0' if EMPTY_BASELINE else '300')
    if '--inspect-zone' in args or '--zone-name-servers' in args:
        spec = importlib.util.spec_from_file_location('check', SOURCE_VALUE)
        check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(check)
        if '--zone-name-servers' in args:
            check.authoritative_servers = lambda: (
                ['wrong.ns.cloudflare.com.', 'ursula.ns.cloudflare.com.'] if failure == 'delegation-mismatch' else
                ['ursula.ns.cloudflare.com.', 'armando.ns.cloudflare.com.'])
        else:
            check.authoritative_servers = lambda: ['mock.ns.cloudflare.com.']
            check.public_answers = lambda server, host, kind: (
                [(host, 'A')] if failure == 'authoritative' and host == 'portal.stinkyboi.com' and kind == 'A' else [])
        try:
            if '--zone-name-servers' in args:
                check.verify_zone_nameservers(json.loads(args[args.index('--zone-name-servers') + 1]))
            else:
                check.inspect_public_zone(check.inventory(),
                    json.loads(Path(args[args.index('--inspect-zone') + 1]).read_text()),
                    json.loads(Path(args[args.index('--current') + 1]).read_text()))
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            sys.exit(1)
    sys.exit(1 if failure == 'preflight' and '--execute' in args else 0)
else:
    method = args[args.index('-X')+1]
    path = urlparse(args[-1])
    with (BASE/'calls.jsonl').open('a') as stream: stream.write(json.dumps([method, path.path, path.query]) + '\n')
    statefile = BASE/'state.json'
    state = json.loads(statefile.read_text())
    if path.path.endswith('/zones'):
        result = [{'id':'zone','name':'stinkyboi.com',
                   'name_servers':['ursula.ns.cloudflare.com', 'armando.ns.cloudflare.com']}]
        if failure == 'delegation-incomplete':
            result[0].pop('name_servers')
        info = {'total_count': 1}
    elif method == 'GET':
        query = parse_qs(path.query)
        if 'name' in query:
            host = query['name'][0]
            result = state.get(host, [])
            if failure == 'read' and host == 'sonarr.stinkyboi.com':
                sys.exit(22)
            if failure == 'wrong-owner-txt' and host == 'sonarr.stinkyboi.com':
                result = result + [{'id':'wrong-txt','name':'other.stinkyboi.com','type':'TXT','content':'retain'}]
            if failure == 'wrong-owner' and host == 'sonarr.stinkyboi.com':
                result = [{**record, 'name':'other.stinkyboi.com'} for record in result]
            if failure == 'target-race' and host == 'sonarr.stinkyboi.com':
                result = []
            count = len(result) + (1 if failure == 'pagination' else 0)
            info = {'total_count': count}
        else:
            all_records = sorted((record for records in state.values() for record in records), key=lambda record: record['id'])
            page = int(query['page'][0])
            result = all_records[(page - 1) * 100:page * 100]
            if failure == 'zone-duplicate' and page == 1:
                result[0] = dict(result[1])
            total = len(all_records) + (1 if failure == 'zone-pagination' else 0)
            info = {'page':page, 'per_page':100, 'count':len(result), 'total_count':total,
                    'total_pages':(total + 99)//100}
            if failure == 'zone-missing-info':
                del info['total_pages']
            if failure in ('target-content-race', 'target-proxy-race', 'target-ttl-race') and page == info['total_pages']:
                record = state['sonarr.stinkyboi.com'][0]
                field, replacement = {
                    'target-content-race': ('content', '100.100.100.9'),
                    'target-proxy-race': ('proxied', True),
                    'target-ttl-race': ('ttl', 120),
                }[failure]
                record[field] = replacement
    elif method == 'DELETE':
        ident = path.path.rsplit('/',1)[1]
        if failure == 'partial' and not (BASE/'failed-once').exists():
            count_file = BASE/'delete-count'
            count = int(count_file.read_text()) if count_file.exists() else 0
            count_file.write_text(str(count + 1))
            if count == 1:
                (BASE/'failed-once').write_text('1')
                sys.exit(22)
        state = {host:[record for record in records if record['id'] != ident]
                 for host, records in state.items()}
        result = {'id':ident}
        info = {'total_count': 1}
    else:
        sys.exit(2)
    statefile.write_text(json.dumps(state))
    print(json.dumps({'success': True, 'result': result, 'result_info': info}))
'''.replace('BASE_VALUE', repr(str(base))).replace('FAILURE_VALUE', repr(failure)).replace(
                'EMPTY_BASELINE', repr(empty_baseline)).replace(
                'SOURCE_VALUE', repr(str(ROOT/'scripts/tailscale-private-dns-check.py')))
            for name in ('git','aws','curl','python3'):
                path = binary/name
                path.write_text(f'#!{sys.executable}\n'+fake)
                path.chmod(0o755)
            environment = dict(os.environ, PATH=str(binary)+os.pathsep+os.environ['PATH'])
            command = ['bash', str(script), '--retire-private']
            if execute:
                command += ['--execute', '--expected-sha', 'a'*40, '--evidence', str(evidence_file)]
            else:
                command += ['--dry-run', '--baseline-out', str(base/'baseline.json')]
            first = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=60)
            if retry:
                second = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=60)
                result = (first, second)
            else:
                result = first
            output = ''.join(item.stdout + item.stderr for item in result) if retry else result.stdout + result.stderr
            self.assertNotIn('fake-secret-must-not-leak', output)
            baseline = json.loads((base/'baseline.json').read_text()) if not execute and first.returncode == 0 else None
            return result, before, json.loads(state.read_text()), [
                json.loads(line) for line in calls.read_text().splitlines()], baseline

    def test_dry_run_generates_private_baseline_and_never_writes(self):
        result, before, after, calls, baseline = self.exercise()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, after)
        self.assertEqual(baseline['previous_ttl_seconds'], 300)
        names = check.retirement_names(check.inventory())
        self.assertEqual(baseline['checked_names'], names)
        self.assertEqual(set(baseline['off_tailnet']), set(names))
        self.assertTrue(all(decision == '' for decision in baseline['off_tailnet'].values()))
        self.assertEqual(len({item['name'] for item in baseline['baseline_records']}), 26)
        self.assertFalse(baseline['owner_tailnet_dns_confirmed'])
        self.assertFalse(any(call[0] in ('DELETE','PUT','POST') for call in calls))
        queried = [parse_qs(call[2])['name'][0] for call in calls
                   if call[0] == 'GET' and '/dns_records' in call[1] and 'name=' in call[2]]
        self.assertEqual(queried, names)
        self.assertEqual(sum(call[0] == 'GET' and 'page' in parse_qs(call[2]) for call in calls), 2)
        self.assertIn('DRY-RUN delete', result.stdout)
        self.assertNotIn('dummy-private-value', result.stdout + result.stderr)

    def test_execute_deletes_only_exact_address_records_and_is_idempotent(self):
        result, before, after, calls, _ = self.exercise(execute=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--execute', calls[0][1])
        names = check.inventory()
        for host in check.retirement_names(names):
            self.assertFalse(any(record['type'] in ('A','AAAA','CNAME') for record in after[host]))
        for host in names['retired_hostnames'] + ['mastodon.stinkyboi.com']:
            self.assertEqual(after[host], before[host])
        self.assertEqual(after['stinkyboi.com'], before['stinkyboi.com'])
        self.assertEqual(after['argocd.stinkyboi.com'], [record for record in before['argocd.stinkyboi.com']
                                                          if record['type'] == 'TXT'])
        self.assertEqual(after['unrelated-0.stinkyboi.com'], before['unrelated-0.stinkyboi.com'])
        self.assertEqual(sum(call[0] == 'DELETE' for call in calls), 28)
        self.assertFalse(any(call[0] in ('PUT','POST') for call in calls))
        self.assertIn('All 26 app subdomains', result.stdout)
        result, before, after, calls, _ = self.exercise(execute=True, already=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(call[0] == 'DELETE' for call in calls), 0)

    def test_missing_public_record_and_fully_retired_baseline_are_valid(self):
        result, _, after, calls, _ = self.exercise(execute=True, missing=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(call[0] == 'DELETE' for call in calls), 27)
        self.assertEqual(after['portal.stinkyboi.com'], [])
        result, _, _, calls, _ = self.exercise(execute=True, empty_baseline=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call[0] == 'DELETE' for call in calls))
        preview, _, _, _, baseline = self.exercise(empty_baseline=True)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(baseline['previous_ttl_seconds'], 0)
        self.assertEqual(baseline['baseline_records'], [])

    def test_failed_preflight_or_incomplete_or_drifted_snapshot_never_writes(self):
        for failure in ('preflight', 'read', 'pagination', 'drift', 'wrong-owner', 'wrong-owner-txt',
                        'zone-pagination', 'zone-missing-info', 'zone-duplicate', 'target-race',
                        'wildcard', 'cname', 'delegation', 'wildcard-delegation', 'child',
                        'delegation-mismatch', 'delegation-incomplete'):
            with self.subTest(failure=failure):
                result, _, after, calls, _ = self.exercise(execute=True, failure=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(call[0] in ('DELETE','PUT','POST') for call in calls))
                self.assertTrue(after)

    def test_partial_failure_retries_from_same_baseline(self):
        (first, second), before, after, calls, _ = self.exercise(execute=True, failure='partial', retry=True)
        self.assertNotEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(sum(call[0] == 'DELETE' for call in calls), 29)
        for host in check.retirement_names(check.inventory()):
            self.assertFalse(any(record['type'] in ('A','AAAA','CNAME') for record in after[host]))

    def test_unexplained_authoritative_answer_blocks_before_delete(self):
        result, _, _, calls, _ = self.exercise(execute=True, failure='authoritative', missing=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unexpected effective public answer source', result.stderr)
        self.assertFalse(any(call[0] == 'DELETE' for call in calls))

    def test_failed_authoritative_ttl_reply_blocks_before_delete(self):
        for failure in ('ttl-servfail', 'ttl-nonauthoritative'):
            with self.subTest(failure=failure):
                result, before, after, calls, _ = self.exercise(execute=True, failure=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Incomplete authoritative DNS inspection', result.stderr)
                self.assertEqual(after, before)
                self.assertFalse(any(call[0] in ('DELETE', 'PUT', 'POST') for call in calls))

    def test_same_id_target_edit_during_zone_scan_blocks_before_delete(self):
        for failure in ('target-content-race', 'target-proxy-race', 'target-ttl-race'):
            with self.subTest(failure=failure):
                result, _, _, calls, _ = self.exercise(execute=True, failure=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('public target records changed during inspection', result.stderr)
                self.assertFalse(any(call[0] in ('DELETE', 'PUT', 'POST') for call in calls))

    def test_old_publication_cli_is_disabled(self):
        result = subprocess.run(['bash', str(ROOT/'scripts/tailscale-private-dns.sh'), '--dry-run'],
                                capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('public publication is disabled', result.stderr)
        result = subprocess.run(['bash', str(ROOT/'scripts/tailscale-private-dns.sh'),
                                 '--retire-private', '--dry-run', '--baseline-out',
                                 str(ROOT/'.tailnet-dns-evidence-should-not-exist.json')],
                                capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('outside the public repository', result.stderr)
        with patch.object(sys, 'argv', ['check', '--retire-hostname', 'old.stinkyboi.com']), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            check.main()


if __name__ == '__main__':
    unittest.main()
