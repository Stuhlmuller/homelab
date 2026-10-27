#!/usr/bin/env python3
"""Offline failure fixtures for the rootless legacy network-namespace probe."""

import errno
import importlib.util
from pathlib import Path
import socket
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).with_name("openclaw-legacy-netns-preflight.py")
spec = importlib.util.spec_from_file_location("legacy_netns_preflight", SOURCE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

IPV4 = "Iface\tDestination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
IPV6 = " ".join(["0" * 32, "00", "0" * 32, "00", "0" * 32, "00", "00000000", "00000000", "00000000", "lo"])
VALID = ("net:[100]", "net:[101]", 1000, 1000, "1000 1000 1\n", ["lo"], IPV4, IPV6)


class FakeSocket:
    def __init__(self, outcome):
        self.outcome = outcome

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def settimeout(self, _):
        pass

    def connect_ex(self, _):
        if isinstance(self.outcome, OSError):
            raise self.outcome
        return self.outcome


class BoundaryTests(unittest.TestCase):
    def test_exact_disposable_namespace_passes(self):
        probe.verify_namespace(*VALID)
        probe.probe_egress(lambda *_: FakeSocket(errno.ENETUNREACH))
        probe.probe_loopback()

    def test_namespace_identity_uid_mapping_and_interfaces_fail_closed(self):
        changes = (
            (0, "net:bad"), (1, VALID[0]), (1, "net:bad"),
            (3, 0), (4, "0 0 1\n"), (4, "1000 1000 2\n"),
            (4, "1000 1000 1\n0 0 1\n"), (4, "invalid\n"),
            (5, []), (5, ["eth0", "lo"]),
            (6, ""), (6, IPV4 + "eth0 0 0 0 0 0 0 0 0 0 0\n"),
            (6, IPV4 + "malformed\n"),
            (7, IPV6.replace(" lo", " eth0")), (7, "malformed"),
        )
        for index, value in changes:
            with self.subTest(index=index, value=value):
                changed = list(VALID)
                changed[index] = value
                with self.assertRaises(probe.Blocked):
                    probe.verify_namespace(*changed)

    def test_egress_requires_no_route_for_every_fixed_destination(self):
        for index in range(len(probe.PROBES)):
            for outcome in (0, errno.ECONNREFUSED, errno.EHOSTUNREACH,
                            errno.ETIMEDOUT):
                calls = 0

                def opened(*_):
                    nonlocal calls
                    current = calls
                    calls += 1
                    return FakeSocket(outcome if current == index else errno.ENETUNREACH)

                with self.subTest(index=index, outcome=outcome), self.assertRaises(probe.Blocked):
                    probe.probe_egress(opened)

    def test_unsupported_ipv6_family_is_safe_but_ipv4_socket_failure_blocks(self):
        def opened(family, _):
            if family == socket.AF_INET6:
                return FakeSocket(OSError(errno.EAFNOSUPPORT, "unsupported"))
            return FakeSocket(errno.ENETUNREACH)

        probe.probe_egress(opened)
        with self.assertRaises(probe.Blocked):
            probe.probe_egress(lambda *_: FakeSocket(OSError(errno.EAFNOSUPPORT, "unsupported")))

    def test_main_requires_all_checks_and_emits_only_fixed_status(self):
        with patch.dict(probe.os.environ, {"PARENT_NETNS": VALID[0], "PARENT_UID": "1000"}):
            with patch.object(probe, "snapshot"), patch.object(probe, "bring_up_loopback"), \
                    patch.object(probe, "probe_loopback"), patch.object(probe, "probe_egress"):
                self.assertEqual(probe.main(), 0)
            for failing in ("snapshot", "bring_up_loopback", "probe_loopback", "probe_egress"):
                with self.subTest(failing=failing):
                    with patch.object(probe, "snapshot"), patch.object(probe, "bring_up_loopback"), \
                            patch.object(probe, "probe_loopback"), patch.object(probe, "probe_egress"):
                        with patch.object(probe, failing, side_effect=probe.Blocked("private detail")):
                            self.assertEqual(probe.main(), 1)
        with patch.dict(probe.os.environ, {"PARENT_NETNS": VALID[0], "PARENT_UID": "0"}):
            self.assertEqual(probe.main(), 1)


if __name__ == "__main__":
    unittest.main()
