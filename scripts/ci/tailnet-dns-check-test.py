#!/usr/bin/env python3
"""Focused read-only DNS handoff checks with no cluster or tailnet writes."""
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("dns_check", ROOT / "scripts/tailnet-dns-check.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
NAMES = json.loads(CHECK.INVENTORY.read_text())["hostnames"]
SERVER = "100.99.16.75"
TRAEFIK = "100.99.16.74"


def services():
    return {
        "tailnet-dns": {"metadata": {"annotations": {
            "tailscale.com/hostname": "homelab-dns", "tailscale.com/tags": "tag:homelab-ingress"}},
            "spec": {"type": "LoadBalancer", "loadBalancerClass": "tailscale", "ports": [
                {"port": 53, "protocol": "TCP"}, {"port": 53, "protocol": "UDP"}]},
            "status": {"loadBalancer": {"ingress": [
                {"hostname": "homelab-dns.tail67beb.ts.net"}, {"ip": SERVER}]}}},
        "traefik-private": {"metadata": {"labels": {"homelab.rst.io/private-dns": "approved"},
            "annotations": {"coredns.io/hostname": ",".join(NAMES)}},
            "status": {"loadBalancer": {"ingress": [
                {"hostname": "homelab-ingress.tail67beb.ts.net"}, {"ip": TRAEFIK}]}}},
    }


def answer(server, hostname, kind, tcp=False):
    if server == "1.1.1.1" or kind in ("MX", "TXT") or hostname == "mastodon.stinkyboi.com":
        if kind == "A":
            return "NXDOMAIN", {"qr", "ra"}, set()
        return "NOERROR", {"qr", "ra"}, {(kind, "public-record")}
    if kind == "AAAA":
        return "NOERROR", {"qr", "aa"}, set()
    return "NOERROR", {"qr", "aa"}, {("A", TRAEFIK)}


class DirectDnsCheck(unittest.TestCase):
    def setUp(self):
        self.services = services()
        self.patches = [
            patch.object(CHECK, "service", side_effect=lambda _, name: self.services[name]),
            patch.object(CHECK, "selected_services", return_value={("traefik", "traefik-private")}),
            patch.object(CHECK.SIGNER, "local_signer", return_value={}),
            patch.object(CHECK.SIGNER, "inspect_target", return_value={
                "signed": True, "dns": "homelab-dns.tail67beb.ts.net"}),
            patch.object(CHECK, "dns_answer", side_effect=answer),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_initial_handoff_checks_all_names_and_both_transports(self):
        with redirect_stdout(io.StringIO()) as output:
            CHECK.verify(SERVER, initial=True)
        self.assertIn("29 approved names", output.getvalue())
        calls = CHECK.dns_answer.call_args_list
        for kind in ("A", "AAAA"):
            self.assertTrue(any(call.args[1:] == ("dns-preflight.cordium.stinkyboi.com", kind, True)
                                for call in calls))
            self.assertTrue(any(call.args[1:] == ("dns-preflight.agents.oce.stinkyboi.com", kind, True)
                                for call in calls))

    def test_routine_check_follows_later_approved_names(self):
        self.services["traefik-private"]["metadata"]["annotations"]["coredns.io/hostname"] = (
            "stinkyboi.com,new-app.foo.stinkyboi.com")
        CHECK.verify(SERVER)
        self.assertTrue(any(call.args[1] == "new-app.foo.stinkyboi.com"
                            for call in CHECK.dns_answer.call_args_list))
        with self.assertRaisesRegex(RuntimeError, "reviewed private hostname"):
            CHECK.verify(SERVER, initial=True)

    def test_wrong_service_or_peer_identity_fails_before_dns(self):
        CHECK.selected_services.return_value.add(("another", "service"))
        with self.assertRaisesRegex(RuntimeError, "Only traefik"):
            CHECK.verify(SERVER)
        CHECK.selected_services.return_value = {("traefik", "traefik-private")}
        with self.assertRaisesRegex(RuntimeError, "differs"):
            CHECK.verify("100.99.16.76")
        CHECK.SIGNER.inspect_target.return_value["signed"] = False
        with self.assertRaisesRegex(RuntimeError, "signed"):
            CHECK.verify(SERVER)

    def test_public_fallthrough_cannot_pass_private_answer(self):
        for cached in (False, True):
            def leaked(server, hostname, kind, tcp=False):
                status, flags, records = answer(server, hostname, kind, tcp)
                if hostname == "stinkyboi.com" and kind == "A" and server == SERVER:
                    return status, {"qr", "ra"} | ({"aa"} if cached else set()), records
                return status, flags, records
            CHECK.dns_answer.side_effect = leaked
            with self.subTest(cached=cached), self.assertRaisesRegex(RuntimeError, "fell through"):
                CHECK.verify(SERVER)

    def test_recursive_empty_aaaa_cannot_pass_private_answer(self):
        def leaked(server, hostname, kind, tcp=False):
            status, flags, records = answer(server, hostname, kind, tcp)
            if hostname == "stinkyboi.com" and kind == "AAAA" and server == SERVER:
                return status, {"qr", "aa", "ra"}, records
            return status, flags, records
        CHECK.dns_answer.side_effect = leaked
        with self.assertRaisesRegex(RuntimeError, "Private AAAA"):
            CHECK.verify(SERVER)

    def test_missing_wildcard_answer_fails(self):
        def missing(server, hostname, kind, tcp=False):
            if hostname == "dns-preflight.cordium.stinkyboi.com" and kind == "A":
                return "NXDOMAIN", {"qr", "aa"}, set()
            return answer(server, hostname, kind, tcp)
        CHECK.dns_answer.side_effect = missing
        with self.assertRaisesRegex(RuntimeError, "dns-preflight.cordium"):
            CHECK.verify(SERVER)

    def test_tcp_or_udp_failure_fails(self):
        for failed_tcp in (False, True):
            def unavailable(server, hostname, kind, tcp=False):
                if server == SERVER and hostname == "stinkyboi.com" and kind == "A" and tcp == failed_tcp:
                    raise RuntimeError("DNS transport unavailable")
                return answer(server, hostname, kind, tcp)
            CHECK.dns_answer.side_effect = unavailable
            with self.subTest(tcp=failed_tcp), self.assertRaisesRegex(RuntimeError, "transport"):
                CHECK.verify(SERVER)

    def test_public_records_must_match(self):
        def changed(server, hostname, kind, tcp=False):
            if server == SERVER and hostname == "stinkyboi.com" and kind == "MX":
                return "NOERROR", {"qr", "ra"}, {("MX", "wrong")}
            return answer(server, hostname, kind, tcp)
        CHECK.dns_answer.side_effect = changed
        with self.assertRaisesRegex(RuntimeError, "Public fallthrough"):
            CHECK.verify(SERVER)

    def test_cached_public_records_may_have_authoritative_flag(self):
        def cached(server, hostname, kind, tcp=False):
            status, flags, records = answer(server, hostname, kind, tcp)
            if server == SERVER and (kind in ("MX", "TXT") or hostname == "mastodon.stinkyboi.com"):
                return status, flags | {"aa"}, records
            return status, flags, records
        CHECK.dns_answer.side_effect = cached
        CHECK.verify(SERVER)


if __name__ == "__main__":
    unittest.main()
