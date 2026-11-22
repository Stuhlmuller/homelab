import copy
import json
import unittest
from unittest.mock import Mock

import lease


class LeaseFixture:
    def __init__(self, holder):
        self.record = {'metadata': {'resourceVersion': '1'}, 'spec': {'holderIdentity': holder}}
        self.events = []
        self.now = 0
        self.healthy = True
        self.put_delay = 0
        self.controller = lease.Leader(
            self, 'me', monotonic=lambda: self.now, boot_ns=lambda: self.now * 1_000_000_000,
            set_fence=lambda deadline=None: self.events.append(('fence', deadline)),
            set_marker=lambda deadline=None: self.events.append(('marker', deadline)), healthy=lambda: self.healthy,
        )

    def get(self):
        return copy.deepcopy(self.record)

    def put(self, record, holder):
        if record != self.record:
            raise RuntimeError('Conflict')
        self.events.append(('lease', holder))
        self.record['spec']['holderIdentity'] = holder
        self.record['metadata']['resourceVersion'] = str(int(self.record['metadata']['resourceVersion']) + 1)
        self.now += self.put_delay

    def get_endpoints(self):
        return {'metadata': {'resourceVersion': self.record['metadata']['resourceVersion']}}

    def publish(self, endpoint, ready):
        self.events.append(('endpoint', ready, endpoint['metadata']['resourceVersion']))


class LeaseTest(unittest.TestCase):
    def test_standby_is_live_without_publishing_and_expires_when_paused(self):
        fixture = LeaseFixture('other')
        self.assertFalse(fixture.controller.live())
        fixture.controller.reconcile()
        self.assertTrue(fixture.controller.live())
        self.assertFalse(fixture.controller.ready())
        fixture.now = 10
        self.assertFalse(fixture.controller.live())
        self.assertEqual(fixture.events, [])

    def test_standby_observes_unchanged_resource_version_before_takeover(self):
        fixture = LeaseFixture('other')
        fixture.controller.reconcile()
        fixture.now = 14
        fixture.controller.reconcile()
        self.assertEqual(fixture.events, [])
        fixture.record['metadata']['resourceVersion'] = '2'
        fixture.now = 15
        fixture.controller.reconcile()
        fixture.now = 29
        fixture.controller.reconcile()
        self.assertEqual(fixture.events, [])
        fixture.now = 30
        fixture.controller.reconcile()
        self.assertEqual(fixture.events, [('lease', 'me'), ('fence', 37_000_000_000), ('marker', 37_000_000_000)])
        self.assertFalse(fixture.controller.ready())

    def test_publishes_only_healthy_and_explicitly_clears_a_failed_endpoint(self):
        fixture = LeaseFixture('')
        fixture.controller.reconcile()
        fixture.now = 2
        fixture.controller.reconcile()
        self.assertTrue(fixture.controller.ready())
        self.assertEqual(fixture.events[-1], ('endpoint', True, '2'))
        fixture.healthy = False
        fixture.now = 4
        fixture.controller.reconcile()
        self.assertEqual(fixture.events[-1], ('endpoint', False, '3'))
        self.assertFalse(fixture.controller.ready())
        fixture.now = 15
        fixture.controller.reconcile()
        self.assertEqual(fixture.events[-3:], [('fence', None), ('marker', None), ('lease', '')])
        fixture.now = 28
        fixture.controller.reconcile()
        self.assertEqual(fixture.record['spec']['holderIdentity'], '')

    def test_late_lease_response_cannot_open_fence(self):
        fixture = LeaseFixture('')
        fixture.put_delay = 7
        with self.assertRaises(RuntimeError):
            fixture.controller.reconcile()
        self.assertEqual(fixture.events, [('lease', 'me')])
        self.assertFalse(fixture.controller.ready())

    def test_readiness_expires_even_if_reconciliation_is_paused(self):
        fixture = LeaseFixture('')
        fixture.controller.reconcile()
        fixture.now = 2
        fixture.controller.reconcile()
        self.assertTrue(fixture.controller.ready())
        fixture.now = 8
        self.assertFalse(fixture.controller.ready())

    def test_clear_only_own_endpoint_and_preserve_version(self):
        api = object.__new__(lease.KubernetesLease)
        api.request = Mock()
        api.endpoint_path = '/slice'
        api.pod = {'kind': 'Pod', 'uid': 'me'}
        api.address = '10.244.1.50'
        incumbent = {'targetRef': {'uid': 'other'}, 'addresses': ['10.244.2.50']}
        resource = {'metadata': {'resourceVersion': 'sample'}, 'endpoints': [incumbent]}
        api.publish(resource, False)
        api.request.assert_not_called()
        api.publish(resource, True)
        method, path, payload = api.request.call_args.args
        self.assertEqual((method, path), ('PUT', '/slice'))
        self.assertEqual(json.loads(payload)['metadata']['resourceVersion'], 'sample')
        self.assertEqual(json.loads(payload)['endpoints'][0]['targetRef']['uid'], 'me')
