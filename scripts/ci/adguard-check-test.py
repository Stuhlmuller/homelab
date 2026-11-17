#!/usr/bin/env python3
"""Synthetic boundary tests; never evidence of live AdGuard acceptance."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

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
        before = {'source_revision': 'a' * 40, 'service_uid': 'service'}
        for after in (before, dict(before, service_uid='replacement')):
            with patch.object(CHECK, 'snapshot', side_effect=[before, after]), \
                    patch.object(CHECK, 'read_password', return_value='fixture1' * 4), \
                    patch.object(CHECK, 'Admin'), patch.object(CHECK, 'verify_admin') as admin, \
                    patch.object(CHECK, 'validate_filter'), \
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

    def test_snapshot_rejects_address_unsigned_or_source_drift(self):
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
        peer = {'signed': True, 'dns': 'homelab-adguard.tail67beb.ts.net',
                'node_key': 'nodekey:' + 'b' * 64, 'rotation_key': 'tlpub:' + 'c' * 64, 'pod_uid': 'proxy'}
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


if __name__ == '__main__':
    unittest.main()
