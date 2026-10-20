#!/usr/bin/env python3
"""Regression coverage for the read-only effective NetworkPolicy inventory."""

import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "inventory", ROOT / "scripts/network-policy-inventory.py"
)
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


def pod(namespace, name, labels, pod_ips=(), pod_ip=None, **spec):
    status = {"phase": "Running"}
    if pod_ips:
        status["podIPs"] = [{"ip": value} for value in pod_ips]
    if pod_ip is not None:
        status["podIP"] = pod_ip
    return {"kind": "Pod", "metadata": {"namespace": namespace, "name": name, "labels": labels},
            "spec": {"serviceAccountName": "workload", "containers": [{
                "name": "app", "securityContext": {"capabilities": {"drop": ["ALL"]}},
            }], **spec},
            "status": status}


def policy(namespace, name, selector, egress=None, policy_types=None, ingress=None):
    spec = {"podSelector": selector}
    if egress is not None:
        spec["egress"] = egress
    if ingress is not None:
        spec["ingress"] = ingress
    if policy_types is not None:
        spec["policyTypes"] = policy_types
    return {
        "kind": "NetworkPolicy",
        "metadata": {"namespace": namespace, "name": name},
        "spec": spec,
    }


class NetworkPolicyInventoryTests(unittest.TestCase):
    def test_pinned_octelium_generated_policy_shapes(self):
        bootstrap = (ROOT / "scripts/octelium-cluster-bootstrap.sh").read_text()
        self.assertIn('version="0.35.0"', bootstrap)
        items = inventory.load_items(ROOT / "clusters/homelab/apps/octelium/"
                                     "generated-networkpolicies.json")
        hashes = {
            f"{item['metadata']['namespace']}/{item['metadata']['name']}":
            hashlib.sha256(json.dumps(item["spec"], sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
            for item in items
        }
        self.assertEqual(hashes, {
            "octelium/octelium-ingress": "98604d834f9b0c583f65f14c8f70195df706044658b21d302f33dc62caae2199",
            "octelium/octelium-nocturne": "5cd2281cdd4996d94b456d65a2f4b244e63bf1a37ed47d0c005ba15d1a3e5a35",
            "octelium/octelium-octovigil": "ab5b0dcb621fc89813ce9dd2833ebf14a8ab0187635140269f486714cfb5ccf1",
            "octelium/svc-upstream": "09c86331a6a384a28f6ed34e5b185c3706efdf18395bd8ef82b44c374a69c4b9",
        })
        self.assertEqual(len(inventory.policies(items, strict=True)), 4)
        self.assertIn("all-ports", inventory.broad_rule(items[3]["spec"]["egress"][0]))

    def test_pinned_cordium_generated_policy_shapes(self):
        manifest = (ROOT / "clusters/homelab/apps/cordium-bootstrap/genesis.yaml").read_text()
        self.assertIn("ghcr.io/octelium/cordium-genesis:0.12.7@sha256:"
                      "bc2911c5c17dc431d6b39471235c5bfe929241979a215a491a97fb53f5bbc401", manifest)
        items = inventory.load_items(ROOT / "clusters/homelab/apps/cordium-bootstrap/"
                                     "generated-networkpolicies.json")
        hashes = {
            f"{item['metadata']['namespace']}/{item['metadata']['name']}":
            hashlib.sha256(json.dumps(item["spec"], sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
            for item in items
        }
        self.assertEqual(hashes, {
            "cordium/ws-main": "3a236c4b99915e3b782080b21343d01d3a37b4006e9055858514456ac6b4618e",
            "octelium/cordium-nocturne": "fb32c2ee1ea55c51743b1d4ffcfedb234c99d003929322ea507e9391351314bf",
            "octelium/cordium-rscserver": "4ce6a7059f9b58a3f3ac6b35c97cb5312da100a9d1aec176a459b40c2e429543",
        })
        self.assertEqual(len(inventory.policies(items, strict=True)), 3)
        self.assertIn("all-ports", inventory.broad_rule(items[0]["spec"]["egress"][0]))

    def test_reports_additive_union_drift_and_exceptions(self):
        narrow = policy("apps", "narrow", {"matchLabels": {"app": "client"}}, [{
            "to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "data"}},
                    "podSelector": {"matchLabels": {"app": "database"}}}],
            "ports": [{"protocol": "TCP", "port": 5432}],
        }])
        dns = policy("apps", "dns", {"matchLabels": {"app": "client"}}, [{
            "to": [{"namespaceSelector": {
                "matchLabels": {"kubernetes.io/metadata.name": "kube-system"},
            },
                    "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}],
            "ports": [{"protocol": "UDP", "port": 53}],
        }], ["Egress"])
        broad = policy("apps", "broad", {"matchLabels": {"app": "broad"}}, [{}], ["Egress"])
        deny = policy("apps", "deny", {"matchLabels": {"app": "deny"}}, [], ["Egress"])
        other_namespace = policy(
            "other", "client", {"matchLabels": {"app": "client"}}, [{}], ["Egress"]
        )
        live_only = policy("apps", "live-only", {"matchLabels": {"app": "client"}}, [], ["Egress"])
        drifted_live = policy("apps", "drifted", {"matchLabels": {"app": "drift"}}, [], ["Egress"])
        drifted_render = policy(
            "apps", "drifted", {"matchLabels": {"app": "drift"}}, [{}], ["Egress"]
        )
        source_only = policy(
            "apps", "source-only", {"matchLabels": {"app": "source"}}, [], ["Egress"]
        )
        reviewed = inventory.policy_fingerprint(inventory.normalized_policy(narrow))
        result = inventory.audit(
            [
                pod("apps", "client", {"app": "client"}),
                pod("apps", "broad", {"app": "broad"}),
                pod("apps", "deny", {"app": "deny"}),
                pod("apps", "unisolated", {"app": "none"}),
                pod("apps", "host", {"app": "none"}, hostNetwork=True),
                pod("apps", "init", {"app": "none"}, initContainers=[{
                    "name": "setup", "securityContext": {"capabilities": {"drop": ["ALL"]}},
                }]),
                pod("apps", "privileged", {"app": "none"}, containers=[{
                    "name": "app", "securityContext": {"privileged": True},
                }]),
                pod("apps", "capability-all", {"app": "none"}, containers=[{
                    "name": "app", "securityContext": {
                        "capabilities": {"add": ["all"], "drop": ["ALL"]},
                    },
                }]),
                pod("apps", "capability-normalized", {"app": "none"}, containers=[{
                    "name": "app", "securityContext": {
                        "capabilities": {"add": ["cap_net_admin"], "drop": ["ALL"]},
                    },
                }]),
                pod("apps", "default-capabilities", {"app": "none"}, containers=[{"name": "app"}]),
                {**pod("apps", "terminating", {"app": "none"}),
                 "metadata": {"namespace": "apps", "name": "terminating", "labels": {"app": "none"},
                              "deletionTimestamp": "2026-10-12T00:00:00Z"}},
                {**pod("apps", "finished", {"app": "none"}), "status": {"phase": "Succeeded"}},
            ],
            [narrow, dns, broad, deny, other_namespace, live_only, drifted_live],
            [[narrow, dns, broad, deny, other_namespace, drifted_render, source_only]],
            namespaces=["apps"],
        )
        client = next(item for item in result["pods"] if item["name"] == "client")
        self.assertEqual(
            client["matchingEgressPolicies"], ["apps/dns", "apps/live-only", "apps/narrow"]
        )
        self.assertEqual(len(client["effectiveEgress"]), 2)
        self.assertIn("apps/live-only", result["liveOnlyPolicies"])
        self.assertIn("apps/source-only", result["sourceOnlyPolicies"])
        self.assertIn("apps/drifted", result["driftedPolicies"])
        self.assertNotIn("other/client", result["liveOnlyPolicies"])
        deny_record = next(item for item in result["pods"] if item["name"] == "deny")
        self.assertEqual(deny_record["effectiveEgress"], [])
        self.assertEqual(deny_record["egressMode"], "deny-all")
        self.assertTrue(any(item["kind"] == "wildcard-egress" and item["policy"] == "apps/broad"
                            for item in result["findings"]))
        self.assertTrue(any(item["kind"] == "unisolated-pod" and item["pod"] == "apps/unisolated"
                            for item in result["findings"]))
        self.assertTrue(any(item["kind"] == "unisolated-pod" and item["pod"] == "apps/terminating"
                            for item in result["findings"]))
        exceptions = {item["pod"]: item["exception"] for item in result["findings"]
                      if item["kind"] == "pod-requires-separate-review"}
        self.assertEqual(exceptions["apps/host"], "host-network")
        self.assertEqual(exceptions["apps/init"], "init-container:setup")
        self.assertEqual(exceptions["apps/privileged"], "privileged-container:app")
        self.assertEqual(exceptions["apps/capability-all"], "capability-ALL:container:app")
        self.assertEqual(
            exceptions["apps/capability-normalized"], "capability-NET_ADMIN:container:app"
        )
        self.assertEqual(
            exceptions["apps/default-capabilities"], "capabilities-not-drop-all:container:app"
        )
        self.assertFalse(any(item["pod"] == "apps/finished" for item in result["findings"]
                             if "pod" in item))
        self.assertFalse(any(
            item.get("policy") == "apps/narrow" and item["kind"] == "unowned-egress-policy"
            for item in result["findings"]
        ))
        self.assertEqual(
            reviewed, inventory.policy_fingerprint(inventory.normalized_policy(narrow))
        )

    def test_defaults_port_protocols_before_drift_comparison(self):
        live = policy("apps", "default-protocol", {}, [{
            "to": [{"ipBlock": {"cidr": "10.1.0.2/32"}}],
            "ports": [{"protocol": "TCP", "port": 443}],
        }], ["Egress"])
        rendered = policy("apps", "default-protocol", {}, [{
            "to": [{"ipBlock": {"cidr": "10.1.0.2/32"}}],
            "ports": [{"port": 443}],
        }], ["Egress"])
        result = inventory.audit([pod("apps", "client", {})], [live], [[rendered]])
        self.assertEqual(result["driftedPolicies"], [])

    def test_generated_ingress_only_policy_blocks_missing_or_drifted_source(self):
        selected = {"matchLabels": {"app": "octelium"}}
        workload = pod("octelium", "workload", {"app": "octelium"})
        deny_egress = policy("octelium", "deny-egress", selected, [], ["Egress"])
        generated = policy("octelium", "generated", selected, policy_types=["Ingress"],
                           ingress=[{"from": [{"podSelector": selected}],
                                     "ports": [{"protocol": "TCP", "port": 8080}]}])
        review = {"policies": [{
            "namespace": "octelium", "name": "deny-egress",
            "sha256": inventory.policy_fingerprint(inventory.normalized_policy(deny_egress)),
        }]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in (("pods", [workload]),
                                ("policies", [deny_egress, generated]),
                                ("render", [deny_egress]), ("review", review)):
                (root / f"{name}.json").write_text(json.dumps(value))
            command = [sys.executable, str(ROOT / "scripts/network-policy-inventory.py"),
                       "--pods", str(root / "pods.json"),
                       "--policies", str(root / "policies.json"),
                       "--render", str(root / "render.json"),
                       "--review", str(root / "review.json"), "--fail-on-findings"]
            missing = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(missing.returncode, 1, missing.stderr)
            self.assertEqual(json.loads(missing.stdout)["findings"], [{
                "kind": "unowned-ingress-policy", "policy": "octelium/generated",
            }])
            changed = policy("octelium", "generated", selected, policy_types=["Ingress"],
                             ingress=[{"from": [{"podSelector": selected}],
                                       "ports": [{"port": 9090}]}])
            (root / "render.json").write_text(json.dumps([deny_egress, changed]))
            drifted = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(drifted.returncode, 1, drifted.stderr)
            self.assertEqual(json.loads(drifted.stdout)["findings"], [{
                "kind": "drifted-ingress-policy", "policy": "octelium/generated",
            }])
            self.assertNotEqual(
                inventory.policy_fingerprint(inventory.normalized_policy(generated)),
                inventory.policy_fingerprint(inventory.normalized_policy(changed)),
            )
            changed["spec"]["ingress"][0]["ports"][0]["port"] = 8080
            (root / "render.json").write_text(json.dumps([deny_egress, changed]))
            matched = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(matched.returncode, 0, matched.stdout + matched.stderr)

    def test_mixed_policy_ingress_drift_has_direction_neutral_finding(self):
        selected = {"matchLabels": {"app": "client"}}
        live = policy("apps", "mixed", selected, [], ["Ingress", "Egress"],
                      [{"ports": [{"port": 8080}]}])
        rendered = policy("apps", "mixed", selected, [], ["Ingress", "Egress"],
                          [{"ports": [{"port": 9090}]}])
        result = inventory.audit([pod("apps", "client", {"app": "client"})],
                                 [live], [[rendered]])
        self.assertEqual(result["driftedPolicies"], ["apps/mixed"])
        self.assertEqual([item for item in result["findings"]
                          if item["kind"].startswith("drifted-")],
                         [{"kind": "drifted-policy", "policy": "apps/mixed"}])

    def test_policy_type_transition_has_direction_neutral_finding(self):
        selected = {"matchLabels": {"app": "client"}}
        ingress = [{"ports": [{"port": 8080}]}]
        live = policy("apps", "transition", selected, policy_types=["Ingress"],
                      ingress=ingress)
        rendered = policy("apps", "transition", selected, [], ["Ingress", "Egress"],
                          ingress)
        result = inventory.audit([pod("apps", "client", {"app": "client"})],
                                 [live], [[rendered]])
        self.assertEqual(result["driftedPolicies"], ["apps/transition"])
        self.assertEqual([item for item in result["findings"]
                          if item["kind"].startswith("drifted-")],
                         [{"kind": "drifted-policy", "policy": "apps/transition"}])

    def test_omitted_policy_types_with_empty_egress_defaults_to_ingress(self):
        live = policy("apps", "empty-egress", {}, [], ["Ingress"])
        rendered = policy("apps", "empty-egress", {}, [])
        result = inventory.audit([pod("apps", "client", {})], [live], [[rendered]])
        self.assertEqual(inventory.normalized_policy(rendered)["policyTypes"], ["Ingress"])
        self.assertEqual(result["driftedPolicies"], [])

    def test_empty_policy_types_defaults_from_nonempty_egress(self):
        live = policy("apps", "empty-types", {}, [{}], ["Ingress", "Egress"])
        rendered = policy("apps", "empty-types", {}, [{}], [])
        result = inventory.audit([pod("apps", "client", {})], [live], [[rendered]])
        self.assertEqual(inventory.normalized_policy(rendered)["policyTypes"],
                         ["Egress", "Ingress"])
        self.assertEqual(result["driftedPolicies"], [])

    def test_not_in_selector_matches_missing_key(self):
        selector = {"matchExpressions": [{
            "key": "app", "operator": "NotIn", "values": ["excluded"],
        }]}
        self.assertTrue(inventory.selector_matches(selector, {}))
        self.assertTrue(inventory.selector_matches(selector, {"app": "included"}))
        self.assertFalse(inventory.selector_matches(selector, {"app": "excluded"}))

    def test_not_in_policy_selector_includes_pods_without_key(self):
        selector = {"matchExpressions": [{
            "key": "scope", "operator": "NotIn", "values": ["excluded"],
        }]}
        item = policy("apps", "not-in", selector, [{
            "to": [{"podSelector": {"matchLabels": {"app": "target"}}}],
            "ports": [{"port": 443}],
        }], ["Egress"])
        result = inventory.audit(
            [pod("apps", "missing", {}), pod("apps", "included", {"scope": "included"}),
             pod("apps", "excluded", {"scope": "excluded"})],
            [item], [[item]],
        )
        pods = {record["name"]: record for record in result["pods"]}
        self.assertEqual(pods["missing"]["matchingEgressPolicies"], ["apps/not-in"])
        self.assertEqual(pods["missing"]["egressMode"], "allow-rules")
        self.assertEqual(pods["excluded"]["matchingEgressPolicies"], [])

    def test_not_in_peer_reaches_pods_without_key(self):
        selector = {"matchExpressions": [{
            "key": "scope", "operator": "NotIn", "values": ["blocked"],
        }]}
        item = policy("apps", "not-in-peer", {"matchLabels": {"app": "client"}}, [{
            "to": [{"podSelector": selector}], "ports": [{"port": 443}],
        }], ["Egress"])
        result = inventory.audit(
            [pod("apps", "client", {"app": "client", "scope": "blocked"}),
             pod("apps", "target-a", {}), pod("apps", "target-b", {"scope": "allowed"})],
            [item], [[item]],
        )
        client = next(record for record in result["pods"] if record["name"] == "client")
        self.assertEqual(client["effectiveWildcards"], ["all-current-pods"])

    def test_normalizes_empty_policy_and_egress_fields_before_drift_comparison(self):
        live = [
            policy("apps", "empty-selectors", {}, [{
                "to": [{"namespaceSelector": {}, "podSelector": {}}],
                "ports": [{"protocol": "TCP", "port": 443}],
            }], ["Egress"]),
            policy("apps", "empty-rule-fields", {}, [{}], ["Egress"]),
            policy("apps", "empty-except", {}, [{
                "to": [{"ipBlock": {"cidr": "10.1.0.2/32"}}],
                "ports": [{"port": 443}],
            }], ["Egress"]),
        ]
        rendered = [
            policy("apps", "empty-selectors", {"matchLabels": {}}, [{
                "to": [{"namespaceSelector": {"matchLabels": {}},
                        "podSelector": {"matchExpressions": []}}],
                "ports": [{"port": 443}],
            }], ["Egress"]),
            policy("apps", "empty-rule-fields", {"matchExpressions": []}, [{
                "to": [], "ports": [],
            }], ["Egress"]),
            policy("apps", "empty-except", {}, [{
                "to": [{"ipBlock": {"cidr": "10.1.0.2/32", "except": []}}],
                "ports": [{"protocol": "TCP", "port": 443}],
            }], ["Egress"]),
        ]
        result = inventory.audit([pod("apps", "client", {})], live, [rendered])
        self.assertEqual(result["driftedPolicies"], [])

    def test_review_hash_and_conflicting_snapshots_fail_closed(self):
        item = policy("apps", "reviewed", {}, [], ["Egress"])
        review = {"policies": [{
            "namespace": "apps",
            "name": "reviewed",
            "sha256": inventory.policy_fingerprint(inventory.normalized_policy(item)),
        }]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            path.write_text(json.dumps(review))
            result = inventory.audit([pod("apps", "client", {})], [item], [[item]], path)
        self.assertFalse(any(
            item["kind"] == "unreviewed-egress-policy" for item in result["findings"]
        ))
        changed = policy("apps", "reviewed", {}, [{}], ["Egress"])
        with self.assertRaisesRegex(ValueError, "Conflicting NetworkPolicy"):
            inventory.policies([item, changed])

    def test_review_does_not_hide_semantic_wildcards(self):
        wildcard = policy("apps", "wildcard", {"matchLabels": {}}, [{
            "to": [{"namespaceSelector": {"matchExpressions": []}}],
            "ports": [{"protocol": "TCP"}],
        }], ["Egress"])
        fingerprint = inventory.policy_fingerprint(inventory.normalized_policy(wildcard))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            path.write_text(json.dumps({"policies": [{
                "namespace": "apps", "name": "wildcard", "sha256": fingerprint,
            }]}))
            result = inventory.audit([pod("apps", "client", {})], [wildcard], [[wildcard]], path)
        finding = next(item for item in result["findings"] if item["kind"] == "wildcard-egress")
        self.assertEqual(
            finding["wildcards"],
            ["all-destinations", "all-namespaces", "all-pods", "all-ports"],
        )

    def test_review_does_not_hide_negative_egress_selectors(self):
        negative = policy("apps", "negative", {}, [{
            "to": [{
                "namespaceSelector": {"matchExpressions": [{
                    "key": "reserved.example/marker", "operator": "DoesNotExist",
                }]},
                "podSelector": {"matchExpressions": [{
                    "key": "reserved.example/marker", "operator": "DoesNotExist",
                }]},
            }],
            "ports": [{"port": 443}],
        }], ["Egress"])
        fingerprint = inventory.policy_fingerprint(inventory.normalized_policy(negative))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            path.write_text(json.dumps({"policies": [{
                "namespace": "apps", "name": "negative", "sha256": fingerprint,
            }]}))
            result = inventory.audit([pod("apps", "client", {})], [negative], [[negative]], path)
        finding = next(item for item in result["findings"] if item["kind"] == "wildcard-egress")
        self.assertEqual(
            finding["wildcards"], [
                "negative-namespace-selector", "negative-pod-selector",
                "unresolved-namespace-selector",
            ]
        )

    def test_review_does_not_hide_broad_peer_selectors(self):
        broad_peer = policy("apps", "broad-peer", {"matchLabels": {"app": "client"}}, [{
            "to": [{"podSelector": {"matchExpressions": [{
                "key": "scope", "operator": "Exists",
            }]}}],
            "ports": [{"port": 443}],
        }], ["Egress"])
        unresolved_namespace = policy(
            "apps", "unresolved-namespace", {"matchLabels": {"app": "client"}}, [{
                "to": [{
                    "namespaceSelector": {"matchExpressions": [{
                        "key": "kubernetes.io/metadata.name", "operator": "Exists",
                    }]},
                    "podSelector": {"matchLabels": {"app": "target"}},
                }],
                "ports": [{"port": 443}],
            }], ["Egress"]
        )
        policies = [broad_peer, unresolved_namespace]
        review = {"policies": [{
            "namespace": item["metadata"]["namespace"],
            "name": item["metadata"]["name"],
            "sha256": inventory.policy_fingerprint(inventory.normalized_policy(item)),
        } for item in policies]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            path.write_text(json.dumps(review))
            result = inventory.audit(
                [pod("apps", "client", {"app": "client", "scope": "all"}),
                 pod("apps", "target-a", {"app": "target", "scope": "all"}),
                 pod("apps", "target-b", {"app": "target", "scope": "all"})],
                policies,
                [policies],
                path,
            )
        wildcards = {
            item["policy"]: item["wildcards"] for item in result["findings"]
            if item["kind"] == "wildcard-egress"
        }
        self.assertEqual(
            wildcards["apps/unresolved-namespace"], ["unresolved-namespace-selector"]
        )
        effective = {item["name"]: item["effectiveWildcards"] for item in result["pods"]}
        self.assertEqual(effective["client"], ["all-current-pods"])

        narrow = policy("apps", "narrow-peer", {"matchLabels": {"app": "client"}}, [{
            "to": [{"podSelector": {"matchLabels": {"app": "target"}}}],
            "ports": [{"port": 443}],
        }], ["Egress"])
        result = inventory.audit(
            [pod("apps", "client", {"app": "client"}),
             pod("apps", "target", {"app": "target"}),
             pod("apps", "other", {"app": "other"})],
            [narrow],
            [[narrow]],
        )
        self.assertFalse(any(
            item["kind"] == "wildcard-egress" and item["policy"] == "apps/narrow-peer"
            for item in result["findings"]
        ))

        split_a = policy("apps", "split-peer-a", {"matchLabels": {"app": "client"}}, [{
            "to": [{"podSelector": {"matchLabels": {"tier": "a"}}}],
            "ports": [{"port": 443}],
        }], ["Egress"])
        split_b = policy("apps", "split-peer-b", {"matchLabels": {"app": "client"}}, [{
            "to": [{"podSelector": {"matchLabels": {"tier": "b"}}}],
            "ports": [{"port": 443}],
        }], ["Egress"])
        result = inventory.audit(
            [pod("apps", "client", {"app": "client", "tier": "a"}),
             pod("apps", "target-a", {"app": "target", "tier": "a"}),
             pod("apps", "target-b", {"app": "target", "tier": "b"})],
            [split_a, split_b],
            [[split_a, split_b]],
        )
        self.assertEqual(result["pods"][0]["effectiveWildcards"], ["all-current-pods"])

        ip_block = policy("apps", "ip-block", {"matchLabels": {"app": "client"}}, [{
            "to": [
                {"ipBlock": {"cidr": "10.244.0.2/32"}},
                {"ipBlock": {"cidr": "10.244.0.3/32"}},
            ],
            "ports": [{"port": 443}],
        }], ["Egress"])
        result = inventory.audit(
            [pod("apps", "client", {"app": "client"}, pod_ip="10.244.0.1"),
             pod("apps", "target-a", {"app": "target"}, pod_ips=["10.244.0.2"]),
             pod("apps", "target-b", {"app": "target"}, pod_ips=["10.244.0.3"])],
            [ip_block],
            [[ip_block]],
        )
        self.assertEqual(result["pods"][0]["effectiveWildcards"], ["all-current-pods"])
        result = inventory.audit(
            [pod("apps", "client", {"app": "client"}, pod_ips=["10.244.0.1"]),
             pod("data", "target-a", {"app": "target"}, pod_ips=["10.244.0.2"]),
             pod("data", "target-b", {"app": "target"}, pod_ips=["10.244.0.3"]),
             pod("other", "unmatched", {"app": "other"}, pod_ips=["10.244.0.4"])],
            [ip_block],
            [[ip_block]],
            namespaces=["apps"],
        )
        self.assertEqual(result["pods"][0]["effectiveWildcards"], ["all-current-pods"])
        result = inventory.audit(
            [pod("apps", "client", {"app": "client"}, pod_ips=["10.244.0.1"]),
             pod("apps", "target-a", {"app": "target"}),
             pod("apps", "target-b", {"app": "target"}, pod_ips=["10.244.0.3"])],
            [ip_block],
            [[ip_block]],
        )
        self.assertEqual(result["pods"][0]["effectiveWildcards"], ["unresolved-pod-ip"])

        mixed = policy("apps", "mixed", {"matchLabels": {"app": "client"}}, [{
            "to": [
                {"podSelector": {"matchLabels": {"app": "target-a"}}},
                {"ipBlock": {"cidr": "10.244.0.4/32"}},
                {"ipBlock": {"cidr": "10.244.0.5/32"}},
            ],
            "ports": [{"port": 443}],
        }], ["Egress"])
        result = inventory.audit(
            [pod("apps", "client", {"app": "client"}, pod_ips=["10.244.0.2"]),
             pod("apps", "target-a", {"app": "target-a"}, pod_ips=["10.244.0.3"]),
             pod("apps", "target-b", {"app": "target-b"}, pod_ips=["10.244.0.4"]),
             pod("apps", "target-c", {"app": "target-c"}, pod_ips=["10.244.0.5"])],
            [mixed],
            [[mixed]],
        )
        self.assertEqual(result["pods"][0]["effectiveWildcards"], ["all-current-pods"])

        cross_namespace = policy("client", "cross-namespace", {}, [{
            "to": [{
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": namespace},
                },
                "podSelector": {"matchLabels": {"scope": "all"}},
            } for namespace in ("one", "two")],
            "ports": [{"port": 443}],
        }], ["Egress"])
        result = inventory.audit(
            [pod("client", "client", {"scope": "all"}),
             pod("one", "one", {"scope": "all"}),
             pod("two", "two", {"scope": "all"})],
            [cross_namespace],
            [[cross_namespace]],
            namespaces=["client"],
        )
        self.assertEqual(result["pods"][0]["effectiveWildcards"], ["all-current-pods"])

    def test_review_does_not_hide_effective_unions(self):
        ipv4_lower = policy("apps", "ipv4-lower", {"matchLabels": {"app": "ipv4"}}, [{
            "to": [{"ipBlock": {"cidr": "0.0.0.0/1"}}], "ports": [{"port": 443}],
        }], ["Egress"])
        ipv4_upper = policy("apps", "ipv4-upper", {"matchLabels": {"app": "ipv4"}}, [{
            "to": [{"ipBlock": {"cidr": "128.0.0.0/1"}}], "ports": [{"port": 443}],
        }], ["Egress"])
        ipv6 = policy("apps", "ipv6", {"matchLabels": {"app": "ipv6"}}, [
            {"to": [{"ipBlock": {"cidr": "::/1"}}], "ports": [{"port": 443}]},
            {"to": [{"ipBlock": {"cidr": "8000::/1"}}], "ports": [{"port": 443}]},
        ], ["Egress"])
        ports = policy("apps", "ports", {"matchLabels": {"app": "ports"}}, [
            {"to": [{"ipBlock": {"cidr": "10.1.0.2/32"}}],
             "ports": [{"protocol": "TCP", "port": 1, "endPort": 32767}]},
            {"to": [{"ipBlock": {"cidr": "10.1.0.2/32"}}],
             "ports": [{"protocol": "TCP", "port": 32768, "endPort": 65535}]},
        ], ["Egress"])
        policies = [ipv4_lower, ipv4_upper, ipv6, ports]
        review = {"policies": [{
            "namespace": item["metadata"]["namespace"],
            "name": item["metadata"]["name"],
            "sha256": inventory.policy_fingerprint(inventory.normalized_policy(item)),
        } for item in policies]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            path.write_text(json.dumps(review))
            result = inventory.audit(
                [pod("apps", "ipv4", {"app": "ipv4"}, pod_ips=["10.1.0.1"]),
                 pod("apps", "ipv6", {"app": "ipv6"}, pod_ips=["2001:db8::1"]),
                 pod("apps", "ports", {"app": "ports"}, pod_ips=["10.1.0.2"])],
                policies,
                [policies],
                path,
            )
        effective = {item["name"]: item["effectiveWildcards"] for item in result["pods"]}
        self.assertEqual(effective["ipv4"], ["all-ip-range"])
        self.assertEqual(effective["ipv6"], ["all-ip-range"])
        self.assertEqual(effective["ports"], ["all-ports"])
        self.assertEqual(
            inventory.broad_rule({
                "to": [{"ipBlock": {"cidr": "0.0.0.0/0", "except": ["10.0.0.0/8"]}}],
                "ports": [{"port": 443}],
            }),
            ["ip-range"],
        )
        self.assertEqual(
            inventory.broad_rule({
                "to": [{"ipBlock": {"cidr": "10.1.0.2/32"}}],
                "ports": [{"port": 1, "endPort": 65534}],
            }),
            ["port-range"],
        )
        self.assertEqual(
            inventory.broad_rule({
                "to": [{"ipBlock": {"cidr": "10.1.0.2/32"}}],
                "ports": [{"port": 1, "endPort": 65535}],
            }),
            ["all-ports"],
        )

    def test_empty_wrong_and_unscoped_snapshots_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "Pod snapshot is empty"):
            inventory.audit([], [], [[]])
        with self.assertRaisesRegex(ValueError, "non-Pod"):
            inventory.audit([{"kind": "Service"}], [], [[]])
        with self.assertRaisesRegex(ValueError, "Candidate namespace"):
            inventory.audit([pod("apps", "client", {})], [], [[]], namespaces=["typo"])

    def test_cli_fails_for_an_unreviewed_wildcard(self):
        broad = policy("apps", "broad", {}, [{}], ["Egress"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pods, policies, rendered = (
                root / name for name in ("pods.json", "policies.json", "render.json")
            )
            pods.write_text(json.dumps({"items": [pod("apps", "client", {})]}))
            policies.write_text(json.dumps({"items": [broad]}))
            rendered.write_text(json.dumps({"items": [broad]}))
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/network-policy-inventory.py"),
                 "--pods", str(pods), "--policies", str(policies), "--render", str(rendered),
                 "--fail-on-findings"],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("wildcard-egress", result.stdout)


if __name__ == "__main__":
    unittest.main()
