#!/usr/bin/env python3
"""Check the trust boundary before signing fixed Kubernetes ingress nodes."""
import copy
import importlib.util
import json
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


def canary_fixture():
    name = "traefik-sidecar-canary"
    revision = name + "-abc"
    source = {"metadata": {"name": name, "namespace": "traefik", "uid": "statefulset-uid",
                           "generation": 1},
              "spec": {"replicas": 1, "serviceName": name,
                       "template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": "acer"},
                                             "serviceAccountName": name}}},
              "status": {"observedGeneration": 1, "readyReplicas": 1,
                         "currentRevision": revision, "updateRevision": revision}}
    pod = {"metadata": {"name": name + "-0", "namespace": "traefik", "uid": "pod-uid",
                        "labels": {"app.kubernetes.io/name": name,
                                   "app.kubernetes.io/instance": name,
                                   "controller-revision-hash": revision},
                        "ownerReferences": [{"apiVersion": "apps/v1", "kind": "StatefulSet",
                                             "name": name, "uid": "statefulset-uid",
                                             "controller": True, "blockOwnerDeletion": True}]},
           "spec": {"nodeName": "acer", "nodeSelector": {"kubernetes.io/hostname": "acer"},
                    "serviceAccountName": name,
                    "containers": [
                        {"name": "traefik", "image": SIGNER.CANARY_IMAGES["traefik"],
                         "args": ["--entrypoints.websecure.address=127.0.0.1:8443",
                                  "--providers.file.directory=/etc/traefik/dynamic"],
                         "volumeMounts": [{"name": "dynamic", "mountPath": "/etc/traefik/dynamic",
                                           "readOnly": True}]},
                        {"name": "tailscale", "image": SIGNER.CANARY_IMAGES["tailscale"],
                         "command": ["/usr/local/bin/tailscaled"],
                         "args": ["--tun=userspace-networking",
                                  "--state=kube:traefik-sidecar-canary-state",
                                  "--statedir=/var/lib/tailscale",
                                  "--socket=/run/tailscale/tailscaled.sock"]}],
                    "volumes": [{"name": "dynamic", "projected": {"sources": [
                        {"configMap": {"name": name + "-routes"}},
                        {"secret": {"name": "traefik-tls"}}]}}]},
           "status": {"conditions": [{"type": "Ready", "status": "True"}],
                      "containerStatuses": [{"name": "traefik", "ready": True},
                                            {"name": "tailscale", "ready": True}]}}
    own = {"ID": "canary-device", "PublicKey": "nodekey:" + "a" * 64,
           "DNSName": "homelab-ingress-canary.tail67beb.ts.net.",
           "Tags": ["tag:homelab-ingress-canary"], "Online": True,
           "TailscaleIPs": ["100.99.16.75"]}
    status = {"BackendState": "Running", "Self": own,
              "CurrentTailnet": {"MagicDNSSuffix": "tail67beb.ts.net"}}
    lock = {"Enabled": True, "NodeKey": own["PublicKey"],
            "PublicKey": "tlpub:" + "b" * 64, "NodeKeySigned": False}
    serve = {"TCP": {"443": {"TCPForward": "127.0.0.1:8443"}}}
    signer = {"VisiblePeers": [], "FilteredPeers": [{"ID": own["ID"],
               "NodeKey": own["PublicKey"], "DNSName": own["DNSName"],
               "Tags": own["Tags"], "TailscaleIPs": own["TailscaleIPs"]}]}
    state_uid = "11111111-2222-3333-4444-555555555555"
    return source, pod, state_uid, status, lock, serve, signer


def canary_policy():
    return {"tagOwners": {"tag:homelab-ingress-canary": ["tag:k8s-operator"]},
            "acls": [], "grants": [{"src": ["autogroup:member"],
                                     "dst": ["tag:homelab-ingress", "10.1.0.0/24"],
                                     "ip": ["*"]}]}


class IngressSigning(unittest.TestCase):
    def validate(self, data):
        return SIGNER.validate_target(SIGNER.TARGETS[0], *data)

    def test_verified_unsigned_target(self):
        result = self.validate(fixture())
        self.assertFalse(result["signed"])
        self.assertEqual(result["node_key"], "nodekey:" + "a" * 64)

    def test_fixed_dns_proxy_identity(self):
        data = fixture()
        data[0]["status"]["loadBalancer"]["ingress"][0]["hostname"] = "homelab-dns.tail67beb.ts.net"
        labels = data[1]["metadata"]["labels"]
        labels["tailscale.com/parent-resource"] = "tailnet-dns"
        labels["tailscale.com/parent-resource-ns"] = "tailnet-dns"
        own = data[2]["Self"]
        own["DNSName"] = "homelab-dns.tail67beb.ts.net."
        own["Tags"] = ["tag:homelab-ingress"]
        data[4]["FilteredPeers"][0]["DNSName"] = own["DNSName"]
        for index, value in [(1, "traefik"), (2, "other-dns"), (3, "tag:homelab-funnel")]:
            changed = copy.deepcopy(data)
            if index == 1:
                changed[1]["metadata"]["labels"]["tailscale.com/parent-resource-ns"] = value
            elif index == 2:
                changed[1]["metadata"]["labels"]["tailscale.com/parent-resource"] = value
            else:
                changed[2]["Self"]["Tags"] = [value]
            with self.subTest(index=index), self.assertRaises(SIGNER.GUARDS.Failure):
                SIGNER.validate_target(SIGNER.TARGETS[4], *changed)
        self.assertFalse(SIGNER.validate_target(SIGNER.TARGETS[4], *data)["signed"])
        data[3]["NodeKeySigned"] = True
        self.assertTrue(SIGNER.validate_target(SIGNER.TARGETS[4], *data)["signed"])

    def test_bulldozer_proxy_is_a_fixed_funnel_target(self):
        self.assertEqual(SIGNER.TARGETS[3],
                         ("traefik", "ingress", "bulldozer-hook", "bulldozer-hook", "tag:homelab-funnel"))

    def test_already_signed_target(self):
        data = fixture()
        data[3]["NodeKeySigned"] = True
        data[4]["VisiblePeers"] = data[4].pop("FilteredPeers")
        self.assertTrue(self.validate(data)["signed"])

    def test_null_filtered_peers_after_all_targets_are_signed(self):
        data = fixture()
        data[3]["NodeKeySigned"] = True
        data[4]["VisiblePeers"] = data[4]["FilteredPeers"]
        data[4]["FilteredPeers"] = None
        self.assertTrue(self.validate(data)["signed"])

    def test_null_visible_peers_before_any_target_is_signed(self):
        data = fixture()
        data[4]["VisiblePeers"] = None
        self.assertFalse(self.validate(data)["signed"])

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

    def test_dns_only_inspects_no_other_proxy(self):
        signed = copy.deepcopy(self.validate(fixture()))
        signed["signed"] = True
        with patch.object(SIGNER.GUARDS, "verify_main", return_value="revision"), \
                patch.object(SIGNER.GUARDS, "command", return_value="https://10.1.0.199:6443"), \
                patch.object(SIGNER, "local_signer", return_value={}), \
                patch.object(SIGNER, "inspect_target", return_value=signed) as inspect:
            SIGNER.reconcile(True, dns_only=True)
        self.assertTrue(all(call.args[0] == SIGNER.TARGETS[4] for call in inspect.call_args_list))

    def test_changed_dns_identity_blocks_signature(self):
        original = self.validate(fixture())
        changed = copy.deepcopy(original)
        changed["pod_uid"] = "rotated-pod"
        with patch.object(SIGNER.GUARDS, "verify_main", return_value="revision"), \
                patch.object(SIGNER.GUARDS, "command", return_value="https://10.1.0.199:6443") as command, \
                patch.object(SIGNER, "local_signer", return_value={}), \
                patch.object(SIGNER, "inspect_target", side_effect=[original, changed]):
            with self.assertRaisesRegex(SIGNER.GUARDS.Failure, "changed"):
                SIGNER.reconcile(True, dns_only=True)
        self.assertFalse(any("sign" in call.args[0] for call in command.call_args_list))

    def test_canary_requires_exact_pod_state_serve_and_peer(self):
        valid = SIGNER.validate_canary(*canary_fixture())
        self.assertEqual(valid["device_id"], "canary-device")
        self.assertEqual(valid["state_uid"], "11111111-2222-3333-4444-555555555555")
        changes = (
            lambda d: d[0]["status"].update(updateRevision="old-revision"),
            lambda d: d[1]["metadata"]["ownerReferences"][0].update(uid="wrong-owner"),
            lambda d: d[1]["spec"].update(nodeName="zimaboard-1"),
            lambda d: d[1]["spec"]["containers"][1]["args"].append("--state=mem:"),
            lambda d: d[1]["spec"]["volumes"][0]["projected"]["sources"].pop(),
            lambda d: d[3]["Self"].update(Tags=["tag:homelab-ingress"]),
            lambda d: d[4].update(NodeKey="nodekey:" + "c" * 64),
            lambda d: d[5]["TCP"].update({"80": {"TCPForward": "127.0.0.1:8000"}}),
            lambda d: d[5]["TCP"]["443"].update(TCPForward="127.0.0.1:9443"),
            lambda d: d[6]["FilteredPeers"][0].update(Tags=["tag:homelab-ingress"]),
        )
        for index, change in enumerate(changes):
            data = copy.deepcopy(canary_fixture())
            change(data)
            with self.subTest(index=index), self.assertRaises(SIGNER.GUARDS.Failure):
                SIGNER.validate_canary(*data)
        data = canary_fixture()
        data = (*data[:2], "", *data[3:])
        with self.assertRaises(SIGNER.GUARDS.Failure):
            SIGNER.validate_canary(*data)

    def test_canary_execute_rechecks_same_identity_before_signing(self):
        original = SIGNER.validate_canary(*canary_fixture())
        changed = copy.deepcopy(original)
        changed["state_uid"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        with patch.object(SIGNER.GUARDS, "verify_main", return_value="revision"), \
                patch.object(SIGNER.GUARDS, "command", return_value="https://10.1.0.199:6443") as command, \
                patch.object(SIGNER, "local_signer", return_value={}), \
                patch.object(SIGNER, "verify_canary_policy"), \
                patch.object(SIGNER, "inspect_canary", side_effect=[original, changed]), \
                patch.object(SIGNER, "inspect_target", side_effect=AssertionError("old target inspected")):
            with self.assertRaisesRegex(SIGNER.GUARDS.Failure, "changed"):
                SIGNER.reconcile(True, canary_only=True)
        self.assertFalse(any("sign" in call.args[0] for call in command.call_args_list))

    def test_canary_execute_signs_only_verified_fixed_node(self):
        original = SIGNER.validate_canary(*canary_fixture())
        signed = copy.deepcopy(original)
        signed["signed"] = True
        with patch.object(SIGNER.GUARDS, "verify_main", return_value="revision"), \
                patch.object(SIGNER.GUARDS, "command", return_value="https://10.1.0.199:6443") as command, \
                patch.object(SIGNER, "local_signer", return_value={}), \
                patch.object(SIGNER, "verify_canary_policy") as policy, \
                patch.object(SIGNER, "inspect_canary", side_effect=[original, original, signed]), \
                patch.object(SIGNER, "inspect_target", side_effect=AssertionError("old target inspected")):
            SIGNER.reconcile(True, canary_only=True)
        signs = [call.args[0] for call in command.call_args_list if "sign" in call.args[0]]
        self.assertEqual(signs, [[SIGNER.TAILSCALE, "lock", "sign", original["node_key"],
                                  original["rotation_key"]]])
        self.assertEqual(policy.call_count, 2)

    def test_canary_signing_requires_live_safe_policy(self):
        good = canary_policy()
        SIGNER.validate_canary_policy(good, copy.deepcopy(good))
        for destination in ("*", "autogroup:tagged", "100.64.0.0/10",
                            "tag:homelab-ingress-canary", "svc:homelab-private-ingress"):
            unsafe = copy.deepcopy(good)
            unsafe["grants"][0]["dst"].append(destination)
            with self.subTest(destination=destination), self.assertRaises(SIGNER.GUARDS.Failure):
                SIGNER.validate_canary_policy(unsafe, copy.deepcopy(unsafe))
        drift = copy.deepcopy(good)
        drift["grants"].append({"src": ["*"], "dst": ["*"], "ip": ["*"]})
        with self.assertRaises(SIGNER.GUARDS.Failure):
            SIGNER.validate_canary_policy(good, drift)

    def test_canary_policy_read_uses_scoped_oauth_and_no_proxy_transport(self):
        policy = canary_policy()
        with patch.object(SIGNER, "read_oauth_credentials", return_value=["client-id", "client-secret"]), \
                patch.object(SIGNER, "ROOT") as root, \
                patch.object(SIGNER.OAUTH, "api_request", side_effect=[
                    {"access_token": "private-token", "token_type": "Bearer"}, policy]) as api:
            root.__truediv__.return_value.read_text.return_value = json.dumps(policy)
            SIGNER.verify_canary_policy()
        self.assertEqual(api.call_args_list[0].args, ("/oauth/token",))
        self.assertEqual(api.call_args_list[0].kwargs["basic"], ("client-id", "client-secret"))
        self.assertEqual(api.call_args_list[1].args, ("/tailnet/-/acl",))
        self.assertEqual(api.call_args_list[1].kwargs["bearer"], "private-token")

    def test_current_broad_policy_stops_before_private_credential_read(self):
        unsafe = canary_policy()
        unsafe["grants"][0]["dst"].append("*")
        with patch.object(SIGNER, "ROOT") as root, \
                patch.object(SIGNER, "read_oauth_credentials") as credentials:
            root.__truediv__.return_value.read_text.return_value = json.dumps(unsafe)
            with self.assertRaises(SIGNER.GUARDS.Failure):
                SIGNER.verify_canary_policy()
        credentials.assert_not_called()

    def test_canary_policy_failure_prevents_signature(self):
        with patch.object(SIGNER.GUARDS, "verify_main", return_value="revision"), \
                patch.object(SIGNER.GUARDS, "command", return_value="https://10.1.0.199:6443") as command, \
                patch.object(SIGNER, "verify_canary_policy", side_effect=SIGNER.GUARDS.Failure("unsafe")):
            with self.assertRaisesRegex(SIGNER.GUARDS.Failure, "unsafe"):
                SIGNER.reconcile(True, canary_only=True)
        self.assertFalse(any("sign" in call.args[0] for call in command.call_args_list))

    def test_canary_policy_drift_after_pod_recheck_prevents_signature(self):
        original = SIGNER.validate_canary(*canary_fixture())
        with patch.object(SIGNER.GUARDS, "verify_main", return_value="revision"), \
                patch.object(SIGNER.GUARDS, "command", return_value="https://10.1.0.199:6443") as command, \
                patch.object(SIGNER, "local_signer", return_value={}), \
                patch.object(SIGNER, "inspect_canary", return_value=original), \
                patch.object(SIGNER, "verify_canary_policy", side_effect=[None, SIGNER.GUARDS.Failure("drift")]):
            with self.assertRaisesRegex(SIGNER.GUARDS.Failure, "drift"):
                SIGNER.reconcile(True, canary_only=True)
        self.assertFalse(any("sign" in call.args[0] for call in command.call_args_list))


if __name__ == "__main__":
    unittest.main()
