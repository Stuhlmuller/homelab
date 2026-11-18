#!/usr/bin/env python3
"""Synthetic boundary tests; never evidence of live AdGuard acceptance."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('check', ROOT / 'scripts/adguard-check.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class DirectCheck(unittest.TestCase):
    def test_direct_receipt_cannot_count_as_client_acceptance(self):
        with self.assertRaises(CHECK.Failure):
            CHECK.validate_client_evidence({'mode': 'direct', 'client_acceptance': False})
        value = {'mode': 'client', 'client_acceptance': True, 'system_resolver': 'socket.getaddrinfo',
                 'cache_method': CHECK.CACHE_METHOD, 'system_sample_count_per_name': 10,
                 'client': {'os': 'Darwin', 'os_version': '15.0', 'client_version': '1.102.4',
                            'accept_dns': True, 'device_id': 'client', 'exit_node_mode': 'none',
                            'exit_node_verified': False}}
        CHECK.validate_client_evidence(value)
        for field in ('os_version', 'client_version', 'exit_node_mode'):
            changed = copy.deepcopy(value)
            changed['client'].pop(field)
            with self.assertRaises(CHECK.Failure):
                CHECK.validate_client_evidence(changed)
        value['client']['exit_node_mode'] = 'selected'
        with self.assertRaises(CHECK.Failure):
            CHECK.validate_client_evidence(value)

    def test_client_requires_real_supported_dns_acceptance_and_exit_metadata(self):
        status = {'BackendState': 'Running', 'Version': '1.102.4',
                  'CurrentTailnet': {'MagicDNSSuffix': 'tail67beb.ts.net'},
                  'Self': {'Online': True, 'ID': 'client', 'DNSName': 'client.tail67beb.ts.net.',
                           'TailscaleIPs': ['100.99.0.7']}}
        prefs = {'CorpDNS': True, 'ExitNodeID': '', 'ExitNodeIP': ''}
        result = CHECK.client_metadata('Darwin', '15.0', status, prefs)
        self.assertEqual(result['exit_node_mode'], 'none')
        self.assertFalse(result['exit_node_verified'])
        for os_name, changed_status, changed_prefs in (
            ('Linux', status, prefs), ('Darwin', status, dict(prefs, CorpDNS=False)),
            ('Darwin', dict(status, Version='unknown'), prefs),
            ('Darwin', status, {'CorpDNS': True}),
            ('Darwin', status, dict(prefs, AutoExitNode='any')),
            ('Darwin', status, dict(prefs, ExitNodeID='exit')),
            ('Darwin', dict(status, Version='1.86.0', ExitNodeStatus={'ID': 'exit', 'Online': True}), dict(prefs, ExitNodeID='exit'))):
            with self.assertRaises(CHECK.Failure):
                CHECK.client_metadata(os_name, '15.0', changed_status, changed_prefs)
        active = dict(status, ExitNodeStatus={'ID': 'exit', 'Online': True})
        self.assertEqual(CHECK.client_metadata('Darwin', '15.0', active, dict(prefs, ExitNodeID='exit'))['exit_node_mode'], 'selected')

    def test_native_resolver_uses_getaddrinfo_without_explicit_server(self):
        with patch.object(CHECK, 'run', return_value='["0.0.0.0"]') as run:
            self.assertEqual(CHECK.system_resolve('ads.example'), {'0.0.0.0'})
        args = run.call_args.args[0]
        self.assertIn('socket.getaddrinfo', args[3])
        self.assertEqual(args[-1], 'ads.example')
        self.assertEqual(run.call_args.kwargs['timeout'], 3)
        self.assertNotIn('dig', args)

    def test_client_samples_flush_each_pair_and_verify_private_and_magicdns(self):
        calls, flushes = [], []
        def resolve(name):
            calls.append(name)
            return {'ads.example': {'0.0.0.0', '::'}, 'example.com': {'93.184.216.34'},
                    'adguard.stinkyboi.com': {'100.99.0.2'},
                    'client.tail67beb.ts.net': {'100.99.0.7'}}[name]
        CHECK.client_samples('ads.example', ['adguard.stinkyboi.com'], '100.99.0.2',
                             'client.tail67beb.ts.net', {'100.99.0.7'}, resolve, lambda: flushes.append(True))
        self.assertEqual(calls.count('ads.example'), 10)
        self.assertEqual(calls.count('example.com'), 10)
        self.assertEqual(len(flushes), 12)
        with self.assertRaises(CHECK.Failure):
            CHECK.client_samples('ads.example', [], '100.99.0.2', 'client.tail67beb.ts.net', {'100.99.0.7'},
                                 lambda _: {'93.184.216.34'}, lambda: None)

    def test_admin_requires_authentication_closed_setup_and_private_history(self):
        valid = ({'name': 'admin'}, {'enabled': False, 'file_enabled': False},
                 {'enabled': False}, [403, 403], 403)
        CHECK.validate_admin(*valid)
        for index, value in ((0, {'name': 'other'}), (1, {'enabled': True, 'file_enabled': False}),
                             (1, {'enabled': False, 'file_enabled': True}), (2, {'enabled': True}),
                             (3, [200, 403]), (3, [403, 400]), (4, 200)):
            data = list(copy.deepcopy(valid))
            data[index] = value
            with self.subTest(index=index), self.assertRaises(CHECK.Failure):
                CHECK.validate_admin(*data)

    def test_acceptance_rechecks_identity_and_never_claims_client_proof(self):
        before = {'source_revision': 'a' * 40, 'service_uid': 'service',
                  'peer': {'lock_enabled': False, 'signed': False, 'node_key': 'nodekey:' + 'b' * 64}}
        for after in (before, dict(before, service_uid='replacement'),
                      dict(before, peer=dict(before['peer'], lock_enabled=True, signed=True)),
                      dict(before, peer=dict(before['peer'], node_key='nodekey:' + 'c' * 64))):
            with patch.object(CHECK, 'snapshot', side_effect=[before, after]), \
                    patch.object(CHECK, 'read_password', return_value='fixture1' * 4), \
                    patch.object(CHECK, 'Admin'), patch.object(CHECK, 'verify_admin') as admin, \
                    patch.object(CHECK, 'validate_filter') as filtering, \
                    patch.object(CHECK.DNS, 'selected_services', return_value={('traefik', 'traefik-private')}), \
                    patch.object(CHECK.DNS, 'service', return_value={}), \
                    patch.object(CHECK.DNS, 'declared_names', return_value=['adguard.stinkyboi.com']), \
                    patch.object(CHECK.DNS, 'published_ip', return_value='100.99.0.2'), \
                    patch.object(CHECK, 'digest', return_value='digest'), \
                    patch.object(CHECK, 'direct_samples') as samples:
                if after == before:
                    result = CHECK.verify('100.99.0.1', Path('/unused'))
                    self.assertEqual(result['mode'], 'direct')
                    self.assertFalse(result['client_acceptance'])
                    self.assertTrue(result['admin_acceptance'])
                    admin.assert_called_once()
                    samples.assert_called_once()
                    self.assertEqual(filtering.call_count, 2)
                else:
                    with self.assertRaisesRegex(CHECK.Failure, 'changed'):
                        CHECK.verify('100.99.0.1', Path('/unused'))

    def test_admin_rejects_redirect_instead_of_forwarding_credentials(self):
        with self.assertRaises(CHECK.Failure):
            CHECK.NoRedirect().redirect_request(None, None, 302, 'redirect', {}, 'https://example.com')

    def test_filter_requires_actual_enabled_list_membership(self):
        status = {'running': True, 'protection_enabled': True, 'version': 'v0.107.80'}
        filters = {'enabled': True, 'interval': 24, 'filters': [
            {'id': 1, 'enabled': True, 'rules_count': 10, 'url': CHECK.FILTER_URL}],
            'whitelist_filters': [], 'user_rules': []}
        match = {'reason': 'FilteredBlackList', 'rules': [{'filter_list_id': 1, 'text': '||ads.example^'}]}
        CHECK.validate_filter(status, filters, match)
        for change in (lambda s, f, m: s.update(protection_enabled=False),
                       lambda s, f, m: s.update(running=False),
                       lambda s, f, m: f['filters'][0].update(rules_count=0),
                       lambda s, f, m: f['filters'][0].update(enabled=False),
                       lambda s, f, m: m.update(reason='NotFilteredNotFound'),
                       lambda s, f, m: m['rules'][0].update(filter_list_id=0),
                       lambda s, f, m: f.update(user_rules=['||ads.example^'])):
            data = copy.deepcopy((status, filters, match))
            change(*data)
            with self.assertRaises(CHECK.Failure):
                CHECK.validate_filter(*data)

    def test_dns_single_attempt_hard_deadline(self):
        response = ';; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n;; flags: qr rd ra;\nexample.com. 30 IN A 93.184.216.34\n'
        with patch.object(CHECK.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, response, '')) as run:
            self.assertEqual(CHECK.dns_answer('100.99.0.1', 'example.com', 'A', True),
                             ('NOERROR', {('A', '93.184.216.34')}))
        self.assertEqual(run.call_args.kwargs['timeout'], 3)
        self.assertIn('+tries=1', run.call_args.args[0])
        self.assertIn('+tcp', run.call_args.args[0])
        with patch.object(CHECK.subprocess, 'run', side_effect=subprocess.TimeoutExpired('dig', 3)) as run:
            with self.assertRaises(CHECK.Failure):
                CHECK.dns_answer('100.99.0.1', 'example.com', 'A')
            self.assertEqual(run.call_count, 1)

    def test_direct_samples_both_transports_and_private_inventory(self):
        calls = []
        def query(server, name, kind, tcp=False):
            calls.append((server, name, kind, tcp))
            if name.endswith('.invalid'):
                return 'NXDOMAIN', set()
            if name == 'ads.example':
                return 'NOERROR', {(kind, '0.0.0.0' if kind == 'A' else '::')}
            if name.endswith('stinkyboi.com'):
                return 'NOERROR', {('A', '100.99.0.2')} if kind == 'A' else set()
            return 'NOERROR', {(kind, '93.184.216.34' if kind == 'A' else '2606:2800:220:1:248:1893:25c8:1946')}
        CHECK.direct_samples('100.99.0.1', ['adguard.stinkyboi.com'], '100.99.0.2', 'ads.example', query)
        for tcp in (False, True):
            self.assertEqual(sum(name == 'ads.example' and kind == 'A' and t == tcp for _, name, kind, t in calls), 10)
            self.assertEqual(sum(name == 'example.com' and kind == 'A' and t == tcp for _, name, kind, t in calls), 10)
        def wrong(*args):
            return 'NOERROR', {('A', '1.1.1.1')}
        with self.assertRaises(CHECK.Failure):
            CHECK.direct_samples('100.99.0.1', [], '100.99.0.2', 'ads.example', wrong)

    def test_credentials_require_private_regular_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'credential'
            path.write_text('fixture1' * 4)
            path.chmod(0o600)
            self.assertEqual(CHECK.read_password(path), 'fixture1' * 4)
            path.chmod(0o644)
            with self.assertRaises(CHECK.Failure):
                CHECK.read_password(path)
            link = Path(temp) / 'link'
            link.symlink_to(path)
            with self.assertRaises(CHECK.Failure):
                CHECK.read_password(link)

    def snapshot_fixture(self):
        source = CHECK.source_documents()
        objects = {key: copy.deepcopy(value) for key, value in source.items()}
        dep = objects[('Deployment', 'adguard')]
        dep['metadata'].update(uid='deployment', generation=1)
        dep['status'] = {'observedGeneration': 1, 'replicas': 1, 'readyReplicas': 1, 'updatedReplicas': 1, 'availableReplicas': 1}
        svc = objects[('Service', 'adguard-dns')]
        svc['metadata']['uid'] = 'service'
        svc['status'] = {'loadBalancer': {'ingress': [{'ip': '100.99.0.1'}]}}
        eso = objects[('ExternalSecret', 'adguard-config')]
        eso['status'] = {'conditions': [{'type': 'Ready', 'status': 'True'}]}
        app = {'spec': {'sources': [{'repoURL': 'https://github.com/Stuhlmuller/homelab.git',
                                  'path': 'clusters/homelab/apps/adguard', 'targetRevision': 'main'}],
                        'project': 'homelab-workloads',
                        'destination': {'namespace': 'automation', 'server': 'https://kubernetes.default.svc'}},
               'status': {'sync': {'status': 'Synced', 'revisions': ['a' * 40]},
                          'health': {'status': 'Healthy'}}}
        peer = {'signed': True, 'lock_enabled': True, 'dns': 'homelab-adguard.tail67beb.ts.net',
                'node_key': 'nodekey:' + 'b' * 64, 'rotation_key': 'tlpub:' + 'c' * 64, 'pod_uid': 'proxy'}
        return source, objects, app, peer

    def test_snapshot_rejects_address_unsigned_or_source_drift(self):
        source, objects, app, peer = self.snapshot_fixture()
        CHECK.validate_snapshot('a' * 40, '100.99.0.1', source, objects, app, peer)
        for change in (lambda o, a, p: p.update(signed=False),
                       lambda o, a, p: a['status']['sync'].update(revisions=['d' * 40]),
                       lambda o, a, p: a['status']['sync'].update(revisions=['a' * 40, 'a' * 40]),
                       lambda o, a, p: a['spec']['sources'].append(a['spec']['sources'][0].copy()),
                       lambda o, a, p: a['spec'].update(source=a['spec']['sources'][0]),
                       lambda o, a, p: a['spec'].update(project='default'),
                       lambda o, a, p: a['spec']['destination'].update(server='https://elsewhere.example'),
                       lambda o, a, p: a['spec']['destination'].update(namespace='default'),
                       lambda o, a, p: o[('Deployment', 'adguard')]['status'].update(readyReplicas=0),
                       lambda o, a, p: o[('ExternalSecret', 'adguard-config')]['spec'].update(refreshPolicy='Periodic'),
                       lambda o, a, p: o[('Service', 'adguard-dns')]['status']['loadBalancer']['ingress'][0].update(ip='100.99.0.3')):
            data = copy.deepcopy((objects, app, peer))
            change(*data)
            with self.assertRaises(CHECK.Failure):
                CHECK.validate_snapshot('a' * 40, '100.99.0.1', source, *data)


    def test_snapshot_requires_explicit_mode_and_matching_signature(self):
        source, objects, app, locked = self.snapshot_fixture()
        for enabled in (False, True):
            peer = dict(locked, lock_enabled=enabled, signed=enabled)
            self.assertEqual(CHECK.validate_snapshot('a' * 40, '100.99.0.1', source, objects, app, peer)['peer'], peer)
        cases = [dict(locked, lock_enabled=v) for v in (None, 0, 1, 'true', 'false')]
        cases += [dict(locked, signed=v) for v in (None, 0, 1, 'true', False)]
        cases += [dict(locked, lock_enabled=False, signed=v) for v in (True, None, 0, 'false')]
        cases += [{k: v for k, v in locked.items() if k != field} for field in ('lock_enabled', 'signed')]
        for peer in cases:
            with self.subTest(peer=peer), self.assertRaises(CHECK.Failure):
                CHECK.validate_snapshot('a' * 40, '100.99.0.1', source, objects, app, peer)

    def test_snapshot_uses_mode_aware_collector_and_retains_source_service_guards(self):
        source, objects, app, locked = self.snapshot_fixture()
        peer = dict(locked, lock_enabled=False, signed=False)
        for change_service in (False, True):
            last = copy.deepcopy(objects[('Service', 'adguard-dns')])
            if change_service:
                last['metadata']['uid'] = 'replacement'
            responses = ['https://10.1.0.199:6443',
                         *[json.dumps(v) for v in objects.values()], json.dumps(app), json.dumps(last)]
            with patch.object(CHECK.SIGNER.GUARDS, 'verify_main', return_value='a' * 40) as main, \
                    patch.object(CHECK, 'source_documents', return_value=source), \
                    patch.object(CHECK, 'run', side_effect=responses), \
                    patch.object(CHECK, 'inspect_adguard_peer', return_value=peer) as inspect, \
                    patch.object(CHECK.SIGNER, 'local_signer', side_effect=AssertionError('legacy direct path')):
                if change_service:
                    with self.assertRaises(CHECK.Failure):
                        CHECK.snapshot('100.99.0.1')
                else:
                    self.assertEqual(CHECK.snapshot('100.99.0.1')['peer'], peer)
                inspect.assert_called_once_with()
                main.assert_called_once_with()

    def test_unlocked_client_still_requires_policy_samples_and_fresh_identity(self):
        client = {'os': 'Darwin', 'os_version': '15.0', 'client_version': '1.102.4',
                  'device_id': 'client', 'accept_dns': True, 'exit_node_mode': 'none',
                  'exit_node_verified': False, 'magic_name': 'client.tail67beb.ts.net',
                  'magic_ips': ['100.99.0.7']}
        peer = {'lock_enabled': False, 'signed': False, 'node_key': 'nodekey:' + 'b' * 64}
        direct = {'source_revision': 'a' * 40, 'peer': peer, 'private_names': ['adguard.stinkyboi.com'],
                  'private_ip': '100.99.0.2', 'admin_acceptance': True}
        desired = {'magic_dns': True, 'override_local_dns': True,
                   'nameservers': [{'address': '100.99.0.1', 'use_with_exit_node': True}]}
        for case in ('valid', 'wrong-policy', 'changed-client', 'changed-mode', 'samples-fail'):
            reader = Mock()
            reader.read.return_value = desired if case != 'wrong-policy' else {}
            control = SimpleNamespace(DNSReader=Mock(return_value=reader),
                                      read_source_policy=Mock(return_value=desired))
            final_client = dict(client, device_id='other') if case == 'changed-client' else client
            fresh = dict(direct, peer=dict(peer, lock_enabled=True, signed=True)) if case == 'changed-mode' else direct
            with patch.object(CHECK, 'inspect_client', side_effect=[client, final_client]) as inspect, \
                    patch.object(CHECK, 'verify', return_value=direct) as verify, \
                    patch.object(CHECK.importlib.util, 'spec_from_file_location', return_value=SimpleNamespace(loader=Mock())), \
                    patch.object(CHECK.importlib.util, 'module_from_spec', return_value=control), \
                    patch.object(CHECK, 'client_samples', side_effect=CHECK.Failure('sample failed') if case == 'samples-fail' else None) as samples, \
                    patch.object(CHECK, 'snapshot', return_value=fresh):
                if case == 'valid':
                    result = CHECK.verify_client('100.99.0.1', Path('/unused'))
                    self.assertTrue(result['client_acceptance'])
                    self.assertTrue(result['admin_acceptance'])
                    self.assertEqual(result['peer'], peer)
                    self.assertEqual(inspect.call_count, 2)
                    self.assertEqual(reader.read.call_count, 2)
                    samples.assert_called_once_with('doubleclick.net', direct['private_names'], direct['private_ip'],
                                                    client['magic_name'], client['magic_ips'])
                else:
                    with self.assertRaises(CHECK.Failure):
                        CHECK.verify_client('100.99.0.1', Path('/unused'))
                verify.assert_called_once_with('100.99.0.1', Path('/unused'), 'doubleclick.net')


class PeerIdentity(unittest.TestCase):
    def setUp(self):
        self.key = 'nodekey:' + 'b' * 64
        self.peer = {'ID': 'device', 'NodeID': 7, 'PublicKey': self.key,
                     'DNSName': 'homelab-adguard.' + CHECK.SIGNER.TAILNET + '.',
                     'Tags': ['tag:homelab-ingress'], 'TailscaleIPs': ['100.99.0.1'],
                     'Online': True, 'InNetworkMap': True}
        self.local = {'BackendState': 'Running',
                      'CurrentTailnet': {'MagicDNSSuffix': CHECK.SIGNER.TAILNET},
                      'Self': {'Online': True, 'PublicKey': 'nodekey:' + 'a' * 64},
                      'Peer': {self.key: copy.deepcopy(self.peer)}}
        self.proxy = {'BackendState': 'Running',
                      'CurrentTailnet': {'MagicDNSSuffix': CHECK.SIGNER.TAILNET},
                      'Self': copy.deepcopy(self.peer)}
        self.lock = {'SchemaVersion': 1, 'Enabled': False}
        self.service = {'metadata': {'name': 'adguard-dns', 'namespace': 'automation', 'uid': 'service'},
                        'status': {'loadBalancer': {'ingress': [
                            {'hostname': self.peer['DNSName'].rstrip('.')}, {'ip': '100.99.0.1'}]}}}
        self.pod = {'metadata': {'name': 'ts-adguard-0', 'namespace': 'tailscale', 'uid': 'pod',
                               'labels': {'tailscale.com/managed': 'true',
                                          'tailscale.com/parent-resource': 'adguard-dns',
                                          'tailscale.com/parent-resource-ns': 'automation',
                                          'tailscale.com/parent-resource-type': 'svc', 'app': 'service'}},
                    'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}

    def arguments(self):
        return [copy.deepcopy(v) for v in [self.local, self.lock, self.service, self.pod, self.proxy, self.lock]]

    def test_unlocked_evidence_has_exact_fields_without_signature(self):
        result = CHECK.validate_unlocked_peer(*self.arguments())
        self.assertEqual(result, {'dns': self.peer['DNSName'].rstrip('.'), 'node_key': self.key,
                                 'pod_uid': 'pod', 'device_id': 'device', 'node_id': 7,
                                 'tags': ['tag:homelab-ingress'], 'addresses': ['100.99.0.1'],
                                 'lock_enabled': False, 'signed': False})
        args = self.arguments()
        args[1]['NodeKey'] = self.local['Self']['PublicKey']
        args[5]['NodeKey'] = self.key
        CHECK.validate_unlocked_peer(*args)

    def test_mode_must_be_an_explicit_boolean(self):
        for value in (None, {}, [], {'Enabled': None}, {'Enabled': 'false'},
                      {'Enabled': 0}, {'Enabled': 1}):
            for index in (1, 5):
                args = self.arguments()
                args[index] = value
                with self.subTest(index=index, value=value), self.assertRaises(CHECK.Failure):
                    CHECK.validate_unlocked_peer(*args)
        for index in (1, 5):
            args = self.arguments()
            args[index]['Enabled'] = True
            with self.assertRaises(CHECK.Failure):
                CHECK.validate_unlocked_peer(*args)
        self.assertIs(CHECK.validate_local_mode(self.local, {'Enabled': True}), True)

    def test_local_and_proxy_availability_and_tailnet(self):
        for index in (0, 4):
            for path, value in ((('BackendState',), 'Stopped'),
                                (('CurrentTailnet', 'MagicDNSSuffix'), 'other.ts.net'),
                                (('Self', 'Online'), False), (('Self', 'Expired'), True)):
                args = self.arguments()
                target = args[index]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.subTest(index=index, path=path), self.assertRaises(CHECK.Failure):
                    CHECK.validate_unlocked_peer(*args)

    def test_every_peer_identity_component_is_bound(self):
        changes = [('ID', ''), ('ID', 'other'), ('NodeID', 0), ('NodeID', True),
                   ('NodeID', -1), ('NodeID', '7'), ('NodeID', 8), ('PublicKey', ''),
                   ('PublicKey', 'nodekey:' + '0' * 64), ('PublicKey', 'nodekey:' + 'c' * 64),
                   ('DNSName', 'other.' + CHECK.SIGNER.TAILNET), ('Tags', []),
                   ('Tags', ['tag:other']), ('Tags', ['tag:homelab-ingress', 'tag:other']),
                   ('TailscaleIPs', []), ('TailscaleIPs', ['100.99.0.2']),
                   ('TailscaleIPs', ['1.1.1.1']), ('TailscaleIPs', ['not-an-ip']),
                   ('TailscaleIPs', ['100.99.0.1', '100.99.0.1']),
                   ('Online', False), ('Expired', True)]
        for side in ('local', 'proxy'):
            for field, value in changes:
                args = self.arguments()
                target = args[0]['Peer'][self.key] if side == 'local' else args[4]['Self']
                target[field] = value
                with self.subTest(side=side, field=field, value=value), self.assertRaises(CHECK.Failure):
                    CHECK.validate_unlocked_peer(*args)
            for field in ('ID', 'NodeID', 'PublicKey', 'DNSName', 'Tags', 'TailscaleIPs', 'Online'):
                args = self.arguments()
                target = args[0]['Peer'][self.key] if side == 'local' else args[4]['Self']
                target.pop(field)
                with self.subTest(side=side, missing=field), self.assertRaises(CHECK.Failure):
                    CHECK.validate_unlocked_peer(*args)

    def test_peer_map_membership_and_uniqueness(self):
        for peers in (None, [], {}, {'wrong-key': self.peer},
                      {self.key: self.peer, 'duplicate': self.peer},
                      {self.key: dict(self.peer, InNetworkMap=False)},
                      {self.key: {k: v for k, v in self.peer.items() if k != 'InNetworkMap'}}):
            args = self.arguments()
            args[0]['Peer'] = peers
            with self.subTest(peers=peers), self.assertRaises(CHECK.Failure):
                CHECK.validate_unlocked_peer(*args)

    def test_ownership_and_published_endpoint(self):
        mutations = [lambda a: a[2]['metadata'].update(uid='other'),
                     lambda a: a[2]['metadata'].update(name='other'),
                     lambda a: a[2]['metadata'].update(namespace='other'),
                     lambda a: a[2]['metadata'].update(deletionTimestamp='now'),
                     lambda a: a[3]['metadata'].update(uid=''),
                     lambda a: a[3]['metadata'].update(namespace='other'),
                     lambda a: a[3]['metadata'].update(deletionTimestamp='now'),
                     lambda a: a[3]['status'].update(conditions=[]),
                     lambda a: a[2]['status']['loadBalancer'].update(ingress=[]),
                     lambda a: a[2]['status']['loadBalancer'].update(ingress=[{'hostname': 'other'}]),
                     lambda a: a[2]['status']['loadBalancer']['ingress'][1].update(ip='100.99.0.2')]
        for label in self.pod['metadata']['labels']:
            mutations.append(lambda a, key=label: a[3]['metadata']['labels'].update({key: 'wrong'}))
        for mutate in mutations:
            args = self.arguments()
            mutate(args)
            with self.assertRaises(CHECK.Failure):
                CHECK.validate_unlocked_peer(*args)

    def test_present_optional_lock_keys_must_match(self):
        for index in (1, 5):
            for key in (None, '', 'nodekey:' + 'c' * 64):
                args = self.arguments()
                args[index]['NodeKey'] = key
                with self.assertRaises(CHECK.Failure):
                    CHECK.validate_unlocked_peer(*args)

    def responses(self):
        return [copy.deepcopy(v) for v in [self.local, self.lock, self.service, {'items': [self.pod]},
                self.proxy, self.lock, self.service, self.local, self.lock]]

    def test_collector_is_fixed_read_only_and_does_not_sign(self):
        with patch.object(CHECK, 'run', side_effect=[json.dumps(v) for v in self.responses()]) as run, \
                patch.object(CHECK.SIGNER, 'local_signer') as signer, \
                patch.object(CHECK.SIGNER, 'inspect_target') as inspect:
            result = CHECK.inspect_adguard_peer()
        signer.assert_not_called()
        inspect.assert_not_called()
        self.assertFalse(result['lock_enabled'])
        self.assertFalse(result['signed'])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[:2], [[CHECK.SIGNER.TAILSCALE, 'status', '--json'],
                                       [CHECK.SIGNER.TAILSCALE, 'lock', 'status', '--json']])
        self.assertEqual(commands[2], ['kubectl', '-n', 'automation', 'get', 'service', 'adguard-dns', '-o', 'json'])
        self.assertEqual(commands[3], ['kubectl', '-n', 'tailscale', 'get', 'pods', '-l',
            'tailscale.com/managed=true,tailscale.com/parent-resource-ns=automation,tailscale.com/parent-resource=adguard-dns,tailscale.com/parent-resource-type=svc', '-o', 'json'])
        prefix = ['kubectl', '-n', 'tailscale', 'exec', 'ts-adguard-0', '-c', 'tailscale', '--', 'tailscale']
        self.assertEqual(commands[4:6], [prefix + ['status', '--json'], prefix + ['lock', 'status', '--json']])
        self.assertEqual(commands[6:], [commands[2], *commands[:2]])

    def test_collector_rejects_changed_mode_service_and_proxy_selection(self):
        for mutate in (lambda r: r[-1].update(Enabled=True),
                       lambda r: r[5].update(Enabled=True),
                       lambda r: r[6]['metadata'].update(uid='replacement'),
                       lambda r: r[3].update(items=[]),
                       lambda r: r[3].update(items=[self.pod, self.pod]),
                       lambda r: r[3]['items'][0]['metadata'].update(name='unexpected')):
            responses = copy.deepcopy(self.responses())
            mutate(responses)
            with patch.object(CHECK, 'run', side_effect=[json.dumps(v) for v in responses]), \
                    self.assertRaises(CHECK.Failure):
                CHECK.inspect_adguard_peer()

    def test_collector_rejects_command_and_json_failure(self):
        for value in ('not-json', 'null', '[]'):
            with patch.object(CHECK, 'run', return_value=value), self.assertRaises(CHECK.Failure):
                CHECK.inspect_adguard_peer()
        with patch.object(CHECK, 'run', side_effect=CHECK.Failure('Command failed')), self.assertRaises(CHECK.Failure):
            CHECK.inspect_adguard_peer()

    def test_enabled_collector_keeps_shared_strict_guards(self):
        signed = {'signed': True, 'dns': self.peer['DNSName'].rstrip('.'), 'node_key': self.key,
                  'rotation_key': 'tlpub:' + 'c' * 64, 'pod_uid': 'pod'}
        for final_mode, signature in ((True, True), (False, True), (True, False)):
            responses = [self.local, {'Enabled': True}, self.local, {'Enabled': final_mode}]
            with patch.object(CHECK, 'run', side_effect=[json.dumps(v) for v in responses]), \
                    patch.object(CHECK.SIGNER, 'local_signer', return_value={'fixture': True}) as signer, \
                    patch.object(CHECK.SIGNER, 'inspect_target', return_value=dict(signed, signed=signature)) as inspect:
                if final_mode and signature:
                    self.assertEqual(CHECK.inspect_adguard_peer(), dict(signed, lock_enabled=True))
                else:
                    with self.assertRaises(CHECK.Failure):
                        CHECK.inspect_adguard_peer()
                signer.assert_called_once_with()
                inspect.assert_called_once_with(CHECK.SIGNER.ADGUARD_TARGET, {'fixture': True})
        for method in ('local_signer', 'inspect_target'):
            with patch.object(CHECK, 'run', side_effect=[json.dumps(self.local), '{"Enabled":true}']), \
                    patch.object(CHECK.SIGNER, 'local_signer', return_value={}), \
                    patch.object(CHECK.SIGNER, 'inspect_target', return_value=signed), \
                    patch.object(CHECK.SIGNER, method, side_effect=CHECK.SIGNER.GUARDS.Failure('strict guard')):
                with self.assertRaises(CHECK.SIGNER.GUARDS.Failure):
                    CHECK.inspect_adguard_peer()


if __name__ == '__main__':
    unittest.main()
