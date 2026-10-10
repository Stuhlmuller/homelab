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
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check", ROOT / "scripts/tailscale-private-dns-check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class Readiness(unittest.TestCase):
    def test_fixed_inventory_covers_apps_and_only_intended_legacy_names(self):
        value = check.inventory()
        apps = 'affine argocd bazarr compass deluge dispatcharr fleet grafana harbor kiali langfuse litellm multica n8n nofx octobot openclaw policy-bot prowlarr radarr sonarr'.split()
        self.assertEqual(set(value['hostnames']), {f'{app}.stinkyboi.com' for app in apps} | {
            'stinkyboi.com', 'cordium.stinkyboi.com', '*.cordium.stinkyboi.com', 'console.stinkyboi.com',
            'octelium.stinkyboi.com', 'octelium-api.stinkyboi.com', 'portal.stinkyboi.com'})
        self.assertEqual(set(value['retired_hostnames']), {f'{name}.stinkyboi.com' for name in (
            'octelium-transport', 'kubernetes-api-ci', 'n8n-webhook', 'policy-bot-hook')})

    def exercise(self, failure=None):
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
                        'TailscaleIPs':['100.100.100.1' if failure != 'peer' else '100.100.100.2']}}})
            host = command[-1].split('/')[2]
            if host == 'octelium-api.stinkyboi.com':
                protocol = next(value.split(': ', 1)[1] for value in command if value.startswith('content-type: '))
                return f'HTTP/2 200\ncontent-type: {protocol}\ngrpc-status: {0 if failure == "grpc" else 16}\n\n200'
            if host == 'harbor.stinkyboi.com':
                realm = 'wrong.example' if failure == 'realm' else host
                return f'HTTP/2 401\nwww-authenticate: Bearer realm="https://{realm}/service/token"\n\n401'
            return 'HTTP/2 503\n\n503' if failure == 'backend' else 'HTTP/2 200\n\n200'

        with patch.object(check, 'run', side_effect=run), contextlib.redirect_stderr(io.StringIO()):
            addresses = check.mesh_addresses()
            check.declared_routes()
            for address in addresses['A'] + addresses['AAAA']:
                check.routes(check.inventory(), address)
        return commands

    def test_readiness_uses_real_host_tls_and_rejects_wrong_mesh_or_upstreams(self):
        commands = self.exercise()
        self.assertEqual(commands[0], ('kubectl', '-n', 'traefik', 'get', 'service', 'traefik-private', '-o', 'json'))
        probes = [command for command in commands if command[0] == 'curl']
        self.assertEqual(len(probes), 29)
        self.assertTrue(all('--connect-to' in command and '--disable' in command and '--insecure' not in command
                            for command in probes))
        for failure in ('hostname', 'unpublished', 'config', 'grpc', 'realm', 'backend', 'address', 'peer'):
            with self.subTest(failure=failure), self.assertRaises(RuntimeError):
                self.exercise(failure)

    def test_execute_checks_reviewed_main_before_readiness(self):
        with patch.object(sys, 'argv', ['check', '--execute', '--expected-sha', 'a'*40]), \
                patch.object(check, 'verify_main', side_effect=RuntimeError('main differs')) as verify, \
                patch.object(check, 'mesh_addresses') as readiness:
            with self.assertRaisesRegex(RuntimeError, 'main differs'):
                check.main()
            verify.assert_called_once_with('a'*40)
            readiness.assert_not_called()

    def test_affine_503_requires_explicit_source_and_live_suspension(self):
        source = {'kind':'Deployment', 'metadata':{'name':'affine'}, 'spec':{'replicas':0}}
        live = {'metadata':{'name':'affine','namespace':'affine'},'spec':{'replicas':0},'status':{'replicas':0}}
        for desired, actual, accepted in ((0,0,True),(1,0,False),(0,1,False),(None,0,False),('0',0,False)):
            source['spec']['replicas'] = desired
            live['spec']['replicas'] = actual
            with self.subTest(desired=desired, actual=actual), patch.object(check, 'run',
                    side_effect=[json.dumps(source), json.dumps(live)]), patch.object(check, 'probe', return_value=(503, [])), \
                    contextlib.redirect_stderr(io.StringIO()):
                if accepted:
                    check.routes({'hostnames':['affine.stinkyboi.com']}, '100.100.100.1')
                else:
                    with self.assertRaisesRegex(RuntimeError, 'readiness failed'):
                        check.routes({'hostnames':['affine.stinkyboi.com']}, '100.100.100.1')
        with patch.object(check, 'probe', return_value=(502, [])), patch.object(check, 'affine_suspended') as suspended:
            with self.assertRaisesRegex(RuntimeError, 'readiness failed'):
                check.routes({'hostnames':['affine.stinkyboi.com']})
            suspended.assert_not_called()

    def test_postcheck_requires_authoritative_and_client_dns_without_connection_override(self):
        commands = []
        addresses = {'A':['100.100.100.1'], 'AAAA':[]}
        def run(*command):
            commands.append(command)
            if command[0] == 'dig':
                if 'NS' in command:
                    return 'test.ns.cloudflare.com.\n'
                host, kind = command[-2:]
                return f'{host}. 300 IN A 100.100.100.1\n' if kind == 'A' else ''
            return 'HTTP/2 200\n\n200'
        value = {'hostnames':['stinkyboi.com'], 'retired_hostnames':[]}
        with patch.object(check, 'run', side_effect=run), patch.object(check.socket, 'getaddrinfo',
                return_value=[(None,None,None,None,('100.100.100.1',443))]), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(check.previous_ttl(value), 300)
            check.verify_dns(value, addresses)
        probes = [command for command in commands if command[0] == 'curl']
        self.assertEqual(len(probes), 1)
        self.assertNotIn('--connect-to', probes[0])
        with patch.object(check, 'run', side_effect=run), patch.object(check.socket, 'getaddrinfo',
                return_value=[(None,None,None,None,('104.16.1.2',443))]), self.assertRaisesRegex(RuntimeError, 'not converged'):
            check.verify_dns(value, addresses)


class DNS(unittest.TestCase):
    def exercise(self, execute=False, failure=None, already=False, retire=False):
        with tempfile.TemporaryDirectory(prefix='private-dns-test-') as directory:
            base = Path(directory)
            script = base/'scripts/tailscale-private-dns.sh'
            script.parent.mkdir()
            shutil.copyfile(ROOT/'scripts/tailscale-private-dns.sh', script)
            (base/'scripts/config').mkdir()
            shutil.copyfile(ROOT/'scripts/config/tailscale-private-dns.json', base/'scripts/config/tailscale-private-dns.json')
            inventory = check.inventory()
            initial = {}
            for index, host in enumerate(inventory['hostnames'] + inventory['retired_hostnames']):
                initial[host] = ([{'id': f'record-{index}', 'name': host, 'type': 'A', 'content': '100.100.100.1',
                                   'proxied': False, 'ttl': 60}] if already and host in inventory['hostnames'] else
                                 [] if already else
                                 [{'id': f'record-{index}', 'name': host, 'type': 'CNAME', 'content': 'old.cfargotunnel.com',
                                   'proxied': True, 'ttl': 1}])
            if already:
                for index, host in enumerate(inventory['hostnames']):
                    initial[host].append({'id': f'v6-{index}', 'name': host, 'type':'AAAA', 'content':'fd7a:115c:a1e0::1', 'proxied':False, 'ttl':60})
            initial[inventory['hostnames'][0]].append({'id': 'keep-txt', 'name': inventory['hostnames'][0], 'type': 'TXT', 'content': 'retain'})
            if not already:
                for index, kind in ((1, 'A'), (2, 'AAAA')):
                    initial[inventory['hostnames'][index]][0].update(
                        type=kind, content='192.0.2.10' if kind == 'A' else '2001:db8::10')
                host = inventory['hostnames'][1]
                initial[host].append({'id':'duplicate-correct-a', 'name':host, 'type':'A',
                                      'content':'100.100.100.1', 'proxied':False, 'ttl':60})
            state = base/'state.json'
            state.write_text(json.dumps(initial))
            calls = base/'calls.jsonl'
            calls.write_text('')
            binary = base/'bin'
            binary.mkdir()
            fake = r'''
import json, os, sys
from pathlib import Path
from urllib.parse import urlparse,parse_qs
BASE = Path(BASE_VALUE)
args = sys.argv[1:]
name = Path(sys.argv[0]).name
failure = FAILURE_VALUE
if name == 'git':
    print(BASE)
elif name == 'aws':
    print('fake-secret-must-not-leak')
elif name == 'python3':
    with (BASE/'calls.jsonl').open('a') as stream: stream.write(json.dumps(['preflight',args])+ '\n')
    if '--addresses-json' in args:
        print(json.dumps({'addresses':{'A':['100.100.100.1'],'AAAA':['fd7a:115c:a1e0::1']},'previous_ttl':300}))
    sys.exit(1 if failure == 'preflight' else 0)
else:
    method = args[args.index('-X')+1]
    path = urlparse(args[-1])
    payload = json.loads(args[args.index('--data')+1]) if '--data' in args else None
    with (BASE/'calls.jsonl').open('a') as stream: stream.write(json.dumps([method,path.path,payload])+ '\n')
    statefile = BASE/'state.json'
    state = json.loads(statefile.read_text())
    if path.path.endswith('/zones'):
        result = [{'id':'zone','name':'stinkyboi.com'}]
    elif method == 'GET':
        host = parse_qs(path.query)['name'][0]
        result = state.get(host,[])
        if failure == 'read' and host == 'sonarr.stinkyboi.com':
            sys.exit(22)
    elif method == 'DELETE':
        ident = path.path.rsplit('/',1)[1]
        state = {host:[record for record in records if record['id'] != ident] for host,records in state.items()}
        result = {'id':ident}
    else:
        host = payload['name']
        payload['id'] = path.path.rsplit('/',1)[1] if method == 'PUT' else 'new-'+payload['type']+'-'+host
        state[host] = [record for record in state[host] if record['id'] != payload['id']] + [payload]
        result = payload
    statefile.write_text(json.dumps(state))
    print(json.dumps({'success': True,'result':result,'result_info':{'total_count':len(result)+ (1 if failure == 'pagination' else 0)}}))
'''.replace('BASE_VALUE', repr(str(base))).replace('FAILURE_VALUE', repr(failure))
            for name in ('git','aws','curl','python3'):
                path = binary/name
                path.write_text(f'#!{sys.executable}\n'+fake)
                path.chmod(0o755)
            environment = dict(os.environ, PATH=str(binary)+os.pathsep+os.environ['PATH'])
            command = ['bash', str(script)] + (['--execute','--expected-sha','a'*40] if execute else [])
            if retire:
                command.append('--retire-old-routes')
            result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=60)
            self.assertNotIn('fake-secret-must-not-leak', result.stdout+result.stderr)
            return result, initial, json.loads(state.read_text()), [json.loads(line) for line in calls.read_text().splitlines()]

    def test_preview_is_read_only_and_execute_is_idempotent_with_verified_records(self):
        result, before, after, calls = self.exercise()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, after)
        self.assertFalse(any(call[0] in ('POST','PUT','DELETE') for call in calls))
        result, before, after, calls = self.exercise(execute=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--execute', calls[0][1])
        value = check.inventory()
        for host in value['hostnames']:
            records = [record for record in after[host] if record['type'] != 'TXT']
            self.assertEqual({(record['type'],record['content'],record['proxied'],record['ttl']) for record in records},
                {('A','100.100.100.1',False,60),('AAAA','fd7a:115c:a1e0::1',False,60)})
        self.assertFalse(any(call[0] == 'preflight' and '--verify-dns' in call[1] for call in calls))
        self.assertIn('scripts/tailscale-private-dns-check.py --verify-dns', result.stdout)
        changes = [call for call in calls if call[0] in ('PUT','POST')]
        self.assertEqual(changes[0][0], 'PUT')
        self.assertEqual(changes[0][2]['type'], 'A')
        self.assertEqual(changes[1][2]['type'], 'AAAA')
        for host in value['retired_hostnames']:
            self.assertEqual(after[host], before[host], 'Initial DNS migration must preserve legacy CI/callback/carrier routes')
        self.assertIn(next(record for record in before['stinkyboi.com'] if record['type'] == 'TXT'), after['stinkyboi.com'])
        result, before, after, calls = self.exercise(execute=True, already=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, after)
        self.assertFalse(any(call[0] in ('POST','PUT','DELETE') for call in calls))

    def test_failed_preflight_or_incomplete_dns_snapshot_never_writes(self):
        for failure in ('preflight','read','pagination'):
            with self.subTest(failure=failure):
                result, before, after, calls = self.exercise(execute=True, failure=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(before, after)
                self.assertFalse(any(call[0] in ('POST','PUT','DELETE') for call in calls))

    def test_preparation_cannot_retire_legacy_routes(self):
        result, before, after, calls = self.exercise(execute=True, retire=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, after)
        self.assertFalse(calls)
        with patch.object(sys, 'argv', ['check', '--retire-old-routes']), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            check.main()


if __name__ == '__main__':
    unittest.main()
