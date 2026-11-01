#!/usr/bin/env python3
"""Offline refusal cases for exact private-ingress Service host approval."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('approval', ROOT / 'scripts/tailscale-service-host-approve.py')
APPROVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APPROVAL)


def policy():
    service = APPROVAL.SERVICE
    return {
        'acls': [],
        'tagOwners': {APPROVAL.TAG: ['tag:k8s-operator']},
        'autoApprovers': {'services': {'tag:ci': ['tag:ci']}},
        'grants': [{'src': ['operator@example.com'], 'dst': [service], 'ip': ['tcp:443']}],
        'tests': [
            {'src': 'operator@example.com', 'accept': [service + ':443']},
            *({'src': source, 'deny': [service + ':443']}
              for source in ('tag:k8s', 'tag:k8s-operator', 'tag:ci')),
        ],
    }


def pod_fixtures():
    sts_uid = '11111111-1111-1111-1111-111111111111'
    pod_uid = '22222222-2222-2222-2222-222222222222'
    state_uid = '33333333-3333-3333-3333-333333333333'
    revision = 'traefik-sidecar-canary-12345678'
    spec = {
        'nodeSelector': {'kubernetes.io/hostname': 'acer'},
        'serviceAccountName': 'traefik-sidecar-canary',
        'automountServiceAccountToken': False,
        'containers': [
            {'name': 'traefik', 'image': APPROVAL.TRAEFIK_IMAGE,
             'args': [*sorted(APPROVAL.CANARY_ENTRYPOINTS),
                      '--providers.file.directory=/etc/traefik/dynamic'],
             'volumeMounts': [{'name': 'dynamic', 'mountPath': '/etc/traefik/dynamic',
                               'readOnly': True}]},
            {'name': 'tailscale', 'image': APPROVAL.TS_IMAGE,
             'command': ['/usr/local/bin/tailscaled'],
             'args': ['--tun=userspace-networking', '--state=kube:' + APPROVAL.STATE,
                      '--statedir=/var/lib/tailscale', '--socket=' + APPROVAL.SOCKET]},
        ],
        'volumes': [{'name': 'dynamic', 'projected': {'sources': [
            {'configMap': {'name': 'traefik-sidecar-canary-routes'}},
            {'secret': {'name': 'traefik-tls'}},
        ]}}],
    }
    sts = {'metadata': {'name': 'traefik-sidecar-canary', 'namespace': 'traefik',
                        'uid': sts_uid, 'generation': 4},
           'spec': {'replicas': 1, 'serviceName': 'traefik-sidecar-canary',
                    'template': {'spec': copy.deepcopy(spec)}},
           'status': {'observedGeneration': 4, 'readyReplicas': 1,
                      'currentRevision': revision, 'updateRevision': revision}}
    pod = {
        'metadata': {'name': APPROVAL.POD, 'namespace': 'traefik', 'uid': pod_uid,
                     'labels': {'app.kubernetes.io/name': 'traefik-sidecar-canary',
                                'app.kubernetes.io/instance': 'traefik-sidecar-canary',
                                'controller-revision-hash': revision},
                     'ownerReferences': [{'apiVersion': 'apps/v1', 'kind': 'StatefulSet',
                                          'name': 'traefik-sidecar-canary',
                                          'uid': sts_uid, 'controller': True}]},
        'spec': {**spec, 'nodeName': 'acer'},
        'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}],
                   'containerStatuses': [{'name': 'traefik', 'ready': True},
                                         {'name': 'tailscale', 'ready': True}]},
    }
    return sts, pod, state_uid


def node_fixtures():
    node_key = 'nodekey:' + 'a' * 64
    tls_key = 'tlpub:' + 'b' * 64
    address = '100.101.102.103'
    dns = APPROVAL.HOST + '.' + APPROVAL.TAILNET
    status = {'BackendState': 'Running', 'CurrentTailnet': {'MagicDNSSuffix': APPROVAL.TAILNET},
              'Self': {'ID': 'n123FAKE', 'PublicKey': node_key, 'Online': True,
                       'DNSName': dns + '.', 'Tags': [APPROVAL.TAG], 'TailscaleIPs': [address]}}
    lock = {'Enabled': True, 'NodeKeySigned': True, 'NodeKey': node_key, 'PublicKey': tls_key}
    serve = {'version': '0.0.1',
             'services': {APPROVAL.SERVICE: {'endpoints': {'tcp:443': 'tcp://127.0.0.1:8443'},
                                             'advertised': True}}}
    device = {'id': '12345', 'nodeId': 'n123FAKE', 'nodeKey': node_key,
              'name': dns, 'hostname': APPROVAL.HOST, 'tags': [APPROVAL.TAG],
              'authorized': True, 'connectedToControl': True, 'isEphemeral': False,
              'addresses': [address], 'tailnetLockError': '',
              'tailnetLockKey': tls_key.replace('tlpub:', 'nlpub:'),
              'clientVersion': '1.102.3'}
    return status, lock, serve, device


class PolicyBoundary(unittest.TestCase):
    def test_scoped_test_client_only(self):
        wanted = policy()
        APPROVAL.policy_contract(wanted, copy.deepcopy(wanted))
        for mutate in (
            lambda p: p['grants'].append({'src': ['tag:ci'], 'dst': ['*'], 'ip': ['*']}),
            lambda p: p['grants'][0]['ip'].__setitem__(0, '*'),
            lambda p: p['grants'][0].__setitem__('via', ['tag:ci']),
            lambda p: p['grants'][0]['src'].__setitem__(0, 'autogroup:member'),
            lambda p: p['grants'][0]['dst'].append(APPROVAL.TAG),
            lambda p: p['autoApprovers']['services'].__setitem__(APPROVAL.SERVICE, [APPROVAL.TAG]),
            lambda p: p['autoApprovers']['services'].__setitem__('*', [APPROVAL.TAG]),
            lambda p: p['grants'].append({'src': ['tag:ci'], 'dst': ['100.100.100.100'], 'ip': ['tcp:443']}),
            lambda p: p['tests'].pop(),
        ):
            bad = copy.deepcopy(wanted)
            mutate(bad)
            with self.subTest(bad=bad), self.assertRaises(APPROVAL.GUARDS.Failure):
                APPROVAL.policy_contract(bad, bad)
        with self.assertRaises(APPROVAL.GUARDS.Failure):
            APPROVAL.policy_contract(wanted, {'grants': []})


class IdentityBoundary(unittest.TestCase):
    def test_exact_service_pod_node_and_pending_host(self):
        self.assertEqual(APPROVAL.service_contract({'name': APPROVAL.SERVICE,
                                                     'ports': ['tcp:443'], 'tags': [],
                                                     'addrs': ['100.100.101.102']}),
                         ('100.100.101.102',))
        sts, pod, state_uid = pod_fixtures()
        ids = APPROVAL.canary_pod_contract(sts, pod, state_uid)
        status, lock, serve, device = node_fixtures()
        APPROVAL.node_contract(status, lock, serve, device, ids)
        APPROVAL.node_contract(status, {**lock, 'PublicKey': lock['PublicKey'].replace('tlpub:', 'nlpub:')},
                               serve, device, ids)
        hosts = {'hosts': [{'stableNodeID': 'n123FAKE', 'approvalLevel': 'not-approved',
                            'configured': 'ready'}]}
        self.assertFalse(APPROVAL.approval_contract(hosts,
                                                     {'approved': False, 'autoApproved': False},
                                                     'n123FAKE'))
        for bad in ({'name': APPROVAL.SERVICE, 'ports': ['tcp:80'], 'tags': [],
                     'addrs': ['100.100.101.102']},
                    {'name': APPROVAL.SERVICE, 'ports': ['tcp:443'], 'tags': ['tag:ci'],
                     'addrs': ['100.100.101.102']},
                    {'name': APPROVAL.SERVICE, 'ports': ['tcp:443'], 'tags': [],
                     'addrs': ['10.1.0.2']}):
            with self.subTest(service=bad), self.assertRaises(APPROVAL.GUARDS.Failure):
                APPROVAL.service_contract(bad)
        for field, value in (('nodeName', 'zimaboard-1'), ('serviceAccountName', 'default'),
                             ('nodeSelector', {'kubernetes.io/hostname': 'zimaboard-1'})):
            bad = copy.deepcopy(pod)
            bad['spec'][field] = value
            with self.subTest(field=field), self.assertRaises(APPROVAL.GUARDS.Failure):
                APPROVAL.canary_pod_contract(sts, bad, state_uid)
        bad = copy.deepcopy(sts)
        bad['spec']['template']['spec']['nodeSelector']['kubernetes.io/hostname'] = 'zimaboard-1'
        with self.assertRaises(APPROVAL.GUARDS.Failure):
            APPROVAL.canary_pod_contract(bad, pod, state_uid)
        for field, value in (('observedGeneration', 3), ('readyReplicas', 0),
                             ('updateRevision', 'traefik-sidecar-canary-new')):
            bad = copy.deepcopy(sts)
            bad['status'][field] = value
            with self.subTest(rollout=field), self.assertRaises(APPROVAL.GUARDS.Failure):
                APPROVAL.canary_pod_contract(bad, pod, state_uid)
        bad = copy.deepcopy(pod)
        bad['metadata']['labels']['controller-revision-hash'] = 'old-revision'
        with self.assertRaises(APPROVAL.GUARDS.Failure):
            APPROVAL.canary_pod_contract(sts, bad, state_uid)
        bad = copy.deepcopy(pod)
        args = bad['spec']['containers'][0]['args']
        args[args.index('--entrypoints.websecure.address=127.0.0.1:8443')] = (
            '--entrypoints.websecure.address=:8443')
        with self.assertRaises(APPROVAL.GUARDS.Failure):
            APPROVAL.canary_pod_contract(sts, bad, state_uid)
        bad = copy.deepcopy(pod)
        bad['spec']['containers'][0]['volumeMounts'][0]['readOnly'] = False
        with self.assertRaises(APPROVAL.GUARDS.Failure):
            APPROVAL.canary_pod_contract(sts, bad, state_uid)
        with self.assertRaises(APPROVAL.GUARDS.Failure):
            APPROVAL.canary_pod_contract(sts, pod, '-' * 36)
        for bad_status, bad_lock, bad_serve, bad_device in (
            ({**status, 'Self': {**status['Self'], 'PublicKey': 'nodekey:' + 'c' * 64}}, lock, serve, device),
            (status, {**lock, 'NodeKeySigned': False}, serve, device),
            (status, lock, {'version': '0.0.1', 'services': {APPROVAL.SERVICE:
                              {'endpoints': {'tcp:80': 'tcp://127.0.0.1:8000'}}}}, device),
            (status, lock, {**serve, 'extra': 'hidden'}, device),
            (status, lock, serve, {**device, 'nodeId': 'nWRONG'}),
            (status, lock, serve, {**device, 'connectedToControl': False}),
            (status, lock, serve, {**device, 'isEphemeral': True}),
            (status, lock, serve, {**device, 'tailnetLockKey': 'tlpub:' + 'c' * 64}),
        ):
            with self.subTest(node=bad_device.get('nodeId')), self.assertRaises(APPROVAL.GUARDS.Failure):
                APPROVAL.node_contract(bad_status, bad_lock, bad_serve, bad_device, ids)
        with self.assertRaises(APPROVAL.GUARDS.Failure):
            APPROVAL.approval_contract({'hosts': [{'stableNodeID': 'nWRONG', 'configured': 'ready'}]},
                                       {'approved': False, 'autoApproved': False}, 'n123FAKE')
        with self.assertRaises(APPROVAL.GUARDS.Failure):
            APPROVAL.approval_contract({'hosts': [{'nodeId': 'n123FAKE', 'approvalLevel': 'pending',
                                                   'configured': 'ready'}]},
                                       {'approved': False, 'autoApproved': False}, 'n123FAKE')
        with self.assertRaises(APPROVAL.GUARDS.Failure):
            APPROVAL.approval_contract(hosts, {'approved': False, 'autoApproved': True}, 'n123FAKE')
        with self.assertRaises(APPROVAL.GUARDS.Failure):
            APPROVAL.approval_contract(hosts, {'approved': True, 'autoApproved': False}, 'n123FAKE')
        self.assertTrue(APPROVAL.approval_contract(
            {'hosts': [{**hosts['hosts'][0], 'approvalLevel': 'approved:manual'}]},
            {'approved': True, 'autoApproved': False}, 'n123FAKE'))

    def test_inspect_uses_current_official_service_api_shape(self):
        wanted = policy()
        sts, pod, state_uid = pod_fixtures()
        status, lock, serve, device = node_fixtures()
        approval_path = APPROVAL.SERVICE_PATH + '/device/n123FAKE/approved'
        responses = {
            '/tailnet/-/acl': wanted,
            APPROVAL.SERVICE_PATH: {'name': APPROVAL.SERVICE, 'ports': ['tcp:443'],
                                    'tags': [], 'addrs': ['100.100.101.102']},
            '/device/n123FAKE': device,
            APPROVAL.SERVICE_PATH + '/devices': {'hosts': [{
                'stableNodeID': 'n123FAKE', 'approvalLevel': 'not-approved',
                'configured': 'ready'}]},
            approval_path: {'approved': False, 'autoApproved': False},
        }

        def command(args, _):
            if 'config' in args:
                return 'https://10.1.0.199:6443'
            if 'secret' in args:
                return state_uid
            raise AssertionError(args)

        def read_json(args, _):
            if 'statefulset' in args:
                return sts
            if 'pods' in args:
                return {'items': [pod]}
            if 'pod' in args:
                return pod
            if 'lock' in args:
                return lock
            if 'get-config' in args:
                return serve
            if 'status' in args:
                return status
            raise AssertionError(args)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'scripts/config').mkdir(parents=True)
            (root / 'scripts/config/tailscale-policy.json').write_text(json.dumps(wanted))
            with (mock.patch.object(APPROVAL, 'ROOT', root),
                  mock.patch.object(APPROVAL.GUARDS, 'command', side_effect=command),
                  mock.patch.object(APPROVAL.GUARDS, 'read_json', side_effect=read_json),
                  mock.patch.object(APPROVAL, 'api_json', side_effect=lambda path, _: responses[path]) as api):
                inspection = APPROVAL.inspect('private-key')
        self.assertFalse(inspection['approved'])
        self.assertEqual(inspection['path'], approval_path)
        self.assertEqual([call.args[0] for call in api.call_args_list], list(responses))


class MutationBoundary(unittest.TestCase):
    def test_execute_rechecks_before_one_exact_post(self):
        pending = {'identity': (('100.100.101.102',), ('sts', 'pod', 'state', 'n123FAKE')),
                   'approved': False, 'path': '/tailnet/-/services/' + APPROVAL.SERVICE +
                   '/device/n123FAKE/approved'}
        approved = {**pending, 'approved': True}
        preview_fingerprint = APPROVAL.fingerprint(pending)
        with (mock.patch.object(APPROVAL.GUARDS, 'verify_main', return_value='a' * 40),
              mock.patch.object(APPROVAL, 'inspect', side_effect=[pending, pending, approved]),
              mock.patch('sys.stdout', new_callable=io.StringIO),
              mock.patch.object(APPROVAL, 'api_json', return_value={'approved': True,
                                                                    'autoApproved': False}) as api):
            APPROVAL.reconcile('private-key', True, preview_fingerprint)
            api.assert_called_once_with(pending['path'], 'private-key', method='POST',
                                        payload={'approved': True})
        with (mock.patch.object(APPROVAL.GUARDS, 'verify_main', return_value='a' * 40),
              mock.patch.object(APPROVAL, 'inspect', side_effect=[pending, {**pending,
                                                                            'identity': ('wrong',)}]),
              mock.patch.object(APPROVAL, 'api_json') as api):
            with self.assertRaises(APPROVAL.GUARDS.Failure):
                APPROVAL.reconcile('private-key', True, preview_fingerprint)
            api.assert_not_called()
        with (mock.patch.object(APPROVAL.GUARDS, 'verify_main', return_value='a' * 40),
              mock.patch.object(APPROVAL, 'inspect', return_value=pending),
              mock.patch.object(APPROVAL, 'api_json') as api):
            with self.assertRaises(APPROVAL.GUARDS.Failure):
                APPROVAL.reconcile('private-key', True, 'f' * 64)
            api.assert_not_called()

    def test_private_key_permissions_and_redirect(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'private'
            directory.mkdir(mode=0o700)
            key = directory / 'key'
            key.write_text(APPROVAL.API_KEY_PREFIX + 'example-private-value')
            key.chmod(0o600)
            self.assertTrue(APPROVAL.read_api_key(key).startswith(APPROVAL.API_KEY_PREFIX))
            key.chmod(0o644)
            with self.assertRaises(APPROVAL.GUARDS.Failure):
                APPROVAL.read_api_key(key)
        with self.assertRaises(APPROVAL.GUARDS.Failure):
            APPROVAL.RefuseRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com')


if __name__ == '__main__':
    unittest.main()
