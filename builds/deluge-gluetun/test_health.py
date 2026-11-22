import struct
import unittest
from unittest.mock import patch

import health


def answer_for(query, flags=0x8180, extra=b''):
    return query[:2] + struct.pack('!5H', flags, 1, 1, 0, 0) + query[12:] + extra


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.commands = []
        self.tunnel = health.TunnelHealth(lambda *args: self.commands.append(args), lambda: self.now)

    def update(self, reachable, rounds=1):
        for _ in range(rounds):
            self.now += health.PERIOD
            self.tunnel.update(reachable)

    def test_health_hysteresis_and_renewal(self):
        self.update(True, 2)
        self.assertEqual(self.tunnel.snapshot(), (False, 0))
        self.update(True)
        self.assertEqual(self.tunnel.snapshot(), (True, 1))
        self.update(False, 2)
        self.assertEqual(self.tunnel.snapshot(), (True, 1))
        self.update(False)
        self.assertEqual(self.tunnel.snapshot(), (False, 2))
        self.update(False, 7)
        self.assertEqual(self.commands, [('renew',)])

    def test_stale_health_is_unready(self):
        self.update(True, 3)
        self.now += health.STALE_AFTER
        self.assertEqual(self.tunnel.snapshot(), (False, 1))

    @patch.object(health, 'doh_query')
    def test_resolver_returns_local_failure_when_transit_is_down(self, upstream):
        query = b'\x19\x42' + health.HEALTH_QUERY[2:]
        answer = health.resolve(self.tunnel, query, udp=True)
        self.assertEqual(health.DNS_HEADER.unpack_from(answer), (0x1942, 0x8182, 1, 0, 0, 0))
        upstream.assert_not_called()

    @patch.object(health, 'doh_query')
    def test_resolver_fallback_and_tcp_for_oversize_reply(self, upstream):
        self.update(True, 3)
        query = b'\x19\x42' + health.HEALTH_QUERY[2:]
        answer = answer_for(query, extra=bytes(550))
        upstream.side_effect = [None, answer, answer]
        udp_answer = health.resolve(self.tunnel, query, udp=True)
        self.assertEqual(health.DNS_HEADER.unpack_from(udp_answer), (0x1942, 0x8380, 1, 0, 0, 0))
        self.assertEqual(health.resolve(self.tunnel, query, udp=False), answer)
        self.assertEqual([call.args[0] for call in upstream.call_args_list], [*health.RESOLVERS, health.RESOLVERS[0]])

    @patch.object(health, 'doh_query')
    def test_probe_requires_successful_dns_answer(self, upstream):
        upstream.side_effect = [answer_for(health.HEALTH_QUERY, flags=0x8182), answer_for(health.HEALTH_QUERY)]
        self.assertTrue(health.probe_tunnel())
        self.assertEqual(upstream.call_count, 2)
