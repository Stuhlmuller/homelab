import struct
import unittest
from unittest.mock import patch

import health


def answer_for(query, flags=0x8180, extra=b""):
    return query[:2] + struct.pack("!5H", flags, 1, 1, 0, 0) + query[12:] + extra


class PathHealthTest(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.commands = []
        self.status = health.PathHealth(lambda *args: self.commands.append(args), lambda: self.now)

    def update(self, a, b, rounds=1):
        for _ in range(rounds):
            self.now += health.PERIOD
            self.status.update({"a": a, "b": b})

    def test_select_survivor_and_blackhole_with_hysteresis(self):
        self.update(True, True, 2)
        self.assertEqual(self.commands, [])
        self.update(True, True)
        self.assertEqual(self.status.resolver_paths(), ("a", "b"))
        self.assertEqual(self.status.resolver_paths(), ("b", "a"))
        self.update(False, True, 2)
        self.update(True, True)
        self.update(False, True, 3)
        self.update(False, False, 3)
        self.update(True, False, 3)
        self.assertEqual(self.commands, [("select", "a", "b"), ("select", "b"), ("select",), ("select", "a")])
        self.assertEqual(self.status.snapshot(), (("a",), {"a": 3, "b": 2}))

    def test_stale_health_is_unready_and_does_not_resolve(self):
        self.update(True, True, 3)
        self.now += health.STALE_AFTER
        self.assertEqual(self.status.snapshot(), ((), {"a": 1, "b": 1}))
        self.assertEqual(self.status.resolver_paths(), ())

    def test_only_unreachable_transit_is_renewed(self):
        self.update(True, False, 10)
        self.assertEqual(self.commands, [("select", "a"), ("renew", "b")])


class ResolverTest(unittest.TestCase):
    query = b"\x19\x42" + health.HEALTH_QUERY[2:]

    @patch.object(health, "doh_query")
    def test_no_upstream_when_both_paths_down(self, upstream):
        status = health.PathHealth()
        answer = health.resolve(status, self.query, udp=True)
        self.assertEqual(health.DNS_HEADER.unpack_from(answer), (0x1942, 0x8182, 1, 0, 0, 0))
        upstream.assert_not_called()

    @patch.object(health, "doh_query")
    def test_fallback_and_tcp_for_oversize_reply(self, upstream):
        answer = answer_for(self.query, extra=bytes(550))
        upstream.side_effect = [None, answer, answer]
        status = health.PathHealth(command=lambda *_: None)
        for _ in range(3):
            status.update({"a": True, "b": False})
        udp_answer = health.resolve(status, self.query, udp=True)
        self.assertEqual(health.DNS_HEADER.unpack_from(udp_answer), (0x1942, 0x8380, 1, 0, 0, 0))
        self.assertEqual(health.resolve(status, self.query, udp=False), answer)
        self.assertEqual([call.args[:2] for call in upstream.call_args_list], [
            ("a", health.RESOLVERS[0]), ("a", health.RESOLVERS[1]), ("a", health.RESOLVERS[0]),
        ])

    @patch.object(health, "doh_query")
    def test_health_requires_successful_dns_answer(self, upstream):
        upstream.side_effect = [answer_for(health.HEALTH_QUERY, flags=0x8182), answer_for(health.HEALTH_QUERY)]
        self.assertTrue(health.probe_path("b"))
        self.assertEqual(upstream.call_count, 2)

    @patch.object(health, "doh_query")
    def test_malformed_dns_is_ignored(self, upstream):
        status = health.PathHealth()
        for packet in (b"bad", self.query[:-4], answer_for(self.query)):
            with self.subTest(packet=packet):
                self.assertIsNone(health.resolve(status, packet, udp=True))
        upstream.assert_not_called()
