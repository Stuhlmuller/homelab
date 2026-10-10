#!/usr/bin/env python3
"""Check the trust boundary before signing fixed Kubernetes ingress nodes."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("signer", ROOT / "scripts/tailscale-ingress-sign.py")
SIGNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIGNER)


def fixture():
    source = {"metadata": {"uid": "source-uid"}, "status": {"loadBalancer": {"ingress": [
        {"hostname": "homelab-ingress.tail67beb.ts.net"}, {"ip": "100.99.16.74"}]}}}
    pod = {"metadata": {"uid": "pod-uid", "labels": {
        "tailscale.com/managed": "true", "tailscale.com/parent-resource": "traefik-private",
        "tailscale.com/parent-resource-ns": "traefik", "tailscale.com/parent-resource-type": "svc",
        "app": "source-uid"}}, "status": {"conditions": [{"type": "Ready", "status": "True"}]}}
    own = {"ID": "node-id", "PublicKey": "nodekey:" + "a" * 64,
           "DNSName": "homelab-ingress.tail67beb.ts.net.", "Tags": ["tag:homelab-ingress"],
           "Online": True, "TailscaleIPs": ["100.99.16.74"]}
    status = {"BackendState": "Running", "Self": own,
              "CurrentTailnet": {"MagicDNSSuffix": "tail67beb.ts.net"}}
    lock = {"Enabled": True, "NodeKey": own["PublicKey"], "PublicKey": "tlpub:" + "b" * 64,
            "NodeKeySigned": False}
    signer = {"VisiblePeers": [], "FilteredPeers": [{"ID": own["ID"], "NodeKey": own["PublicKey"],
               "DNSName": own["DNSName"], "TailscaleIPs": own["TailscaleIPs"]}]}
    return source, pod, status, lock, signer


class IngressSigning(unittest.TestCase):
    def validate(self, data):
        return SIGNER.validate_target(SIGNER.TARGETS[0], *data)

    def test_verified_unsigned_target(self):
        result = self.validate(fixture())
        self.assertFalse(result["signed"])
        self.assertEqual(result["node_key"], "nodekey:" + "a" * 64)

    def test_already_signed_target(self):
        data = fixture()
        data[3]["NodeKeySigned"] = True
        data[4]["VisiblePeers"] = data[4].pop("FilteredPeers")
        self.assertTrue(self.validate(data)["signed"])

    def test_wrong_owner_or_unready_pod(self):
        for field, value in [("app", "another-resource"), ("tailscale.com/parent-resource", "fleet")]:
            with self.subTest(field=field):
                data = fixture()
                data[1]["metadata"]["labels"][field] = value
                with self.assertRaises(SIGNER.GUARDS.Failure):
                    self.validate(data)
        data = fixture()
        data[1]["status"]["conditions"] = []
        with self.assertRaises(SIGNER.GUARDS.Failure):
            self.validate(data)

    def test_mismatched_public_identity(self):
        for field, value in [("Tags", ["tag:k8s"]), ("DNSName", "fleet.tail67beb.ts.net."),
                             ("PublicKey", "nodekey:" + "c" * 64), ("Online", False),
                             ("TailscaleIPs", ["10.1.0.199"])]:
            with self.subTest(field=field):
                data = fixture()
                data[2]["Self"][field] = value
                with self.assertRaises(SIGNER.GUARDS.Failure):
                    self.validate(data)

    def test_coordination_key_must_match_kubernetes(self):
        data = fixture()
        data[4]["FilteredPeers"][0]["NodeKey"] = "nodekey:" + "c" * 64
        with self.assertRaises(SIGNER.GUARDS.Failure):
            self.validate(data)

    def test_ambiguous_or_missing_peer(self):
        for peers in [[], fixture()[4]["FilteredPeers"] * 2]:
            with self.subTest(peers=len(peers)):
                data = fixture()
                data[4]["FilteredPeers"] = peers
                with self.assertRaises(SIGNER.GUARDS.Failure):
                    self.validate(data)

    def test_disabled_lock_and_wrong_published_address(self):
        data = fixture()
        data[3]["Enabled"] = False
        with self.assertRaises(SIGNER.GUARDS.Failure):
            self.validate(data)
        data = fixture()
        data[0]["status"]["loadBalancer"]["ingress"][1]["ip"] = "100.99.16.75"
        with self.assertRaises(SIGNER.GUARDS.Failure):
            self.validate(data)

    def test_untrusted_local_device_fails(self):
        data = fixture()
        lock = {"Enabled": True, "NodeKeySigned": True, "PublicKey": "tlpub:" + "b" * 64,
                "TrustedKeys": [{"Public": "tlpub:" + "c" * 64}]}
        with patch.object(SIGNER.GUARDS, "read_json", side_effect=[data[2], lock]):
            with self.assertRaises(SIGNER.GUARDS.Failure):
                SIGNER.local_signer()

    def test_no_signature_if_any_preflight_fails(self):
        valid = self.validate(fixture())
        with patch.object(SIGNER.GUARDS, "verify_main", return_value="revision"), \
                patch.object(SIGNER.GUARDS, "command", return_value="https://10.1.0.199:6443") as command, \
                patch.object(SIGNER, "local_signer", return_value={}), \
                patch.object(SIGNER, "inspect_target", side_effect=[valid, SIGNER.GUARDS.Failure("bad proxy")]):
            with self.assertRaises(SIGNER.GUARDS.Failure):
                SIGNER.reconcile(True)
        self.assertFalse(any("sign" in call.args[0] for call in command.call_args_list))

    def test_already_signed_reconcile_is_noop(self):
        signed = copy.deepcopy(self.validate(fixture()))
        signed["signed"] = True
        with patch.object(SIGNER.GUARDS, "verify_main", return_value="revision"), \
                patch.object(SIGNER.GUARDS, "command", return_value="https://10.1.0.199:6443") as command, \
                patch.object(SIGNER, "local_signer", return_value={}), \
                patch.object(SIGNER, "inspect_target", return_value=signed):
            SIGNER.reconcile(True)
        self.assertFalse(any("sign" in call.args[0] for call in command.call_args_list))


if __name__ == "__main__":
    unittest.main()
