#!/usr/bin/env python3
"""Check the runner policy's UID boundary and private-address exclusions offline."""
import ipaddress
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / ".cordium/runner-network-policy.json").read_text())


def internet_allowed(address, port):
    destination = ipaddress.ip_address(address)
    for rule in POLICY["spec"]["egress"]:
        if {"protocol": "TCP", "port": port} not in rule["ports"]:
            continue
        for peer in rule["to"]:
            block = peer.get("ipBlock")
            if block and destination in ipaddress.ip_network(block["cidr"]):
                if not any(destination in ipaddress.ip_network(excluded) for excluded in block.get("except", [])):
                    return True
    return False


class Boundary(unittest.TestCase):
    def test_one_workspace_only_and_no_unsolicited_ingress(self):
        self.assertEqual(POLICY["metadata"]["namespace"], "cordium")
        self.assertEqual(POLICY["spec"]["podSelector"]["matchLabels"], {"octelium.com/workspace-uid": "RENDERED-WORKSPACE-UID"})
        self.assertEqual(POLICY["spec"]["ingress"], [])
        self.assertEqual(POLICY["spec"]["policyTypes"], ["Ingress", "Egress"])

    def test_public_web_ports_and_required_dns_only(self):
        for address in ("1.1.1.1", "2606:4700:4700::1111"):
            for port in (80, 443):
                self.assertTrue(internet_allowed(address, port))
            for port in (22, 8080, 6443, 50000):
                self.assertFalse(internet_allowed(address, port))
        dns = POLICY["spec"]["egress"][0]
        self.assertEqual(dns["ports"], [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}])
        self.assertEqual(dns["to"][0], {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}, "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}})

    def test_lan_cluster_tailnet_metadata_loopback_and_ipv6_local_denied(self):
        for address in ("10.1.0.199", "10.244.1.10", "172.16.0.1", "192.168.1.1", "100.100.100.100", "169.254.169.254", "127.0.0.1", "224.0.0.1", "fd00::1", "fe80::1", "::1", "2001:db8::1"):
            for port in (80, 443, 6443):
                self.assertFalse(internet_allowed(address, port), (address, port))


if __name__ == "__main__":
    unittest.main()
