#!/usr/bin/env python3
"""Keep source NetworkPolicy peers aligned with the declared routes."""

import json
from pathlib import Path
import subprocess
import unittest
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
APPS = ROOT / "clusters/homelab/apps"


def documents(path):
    return json.loads(subprocess.check_output([
        "yq", "eval-all", "-o=json", ". as $doc ireduce ([]; . + [$doc])",
        str(path),
    ], text=True))


def nested_yaml(source):
    return json.loads(subprocess.run(
        ["yq", "-o=json", "."], input=source, text=True,
        capture_output=True, check=True,
    ).stdout)


def policy(app, name):
    return next(item["spec"] for item in documents(APPS / app / "networkpolicy.yaml")
                if item["metadata"]["name"] == name)


def peer(namespace, labels=None, expression=None):
    result = {"namespaceSelector": {"matchLabels": {
        "kubernetes.io/metadata.name": namespace}}}
    if labels:
        result["podSelector"] = {"matchLabels": labels}
    if expression:
        result["podSelector"] = {"matchExpressions": [expression]}
    return result


class PeerTests(unittest.TestCase):
    def test_cloudflared_targets_only_declared_cluster_services(self):
        egress = policy("octelium-public", "cloudflared-egress")["egress"]
        gateway = next(rule for rule in egress if rule["ports"] == [
            {"protocol": "TCP", "port": 443}])
        self.assertEqual(gateway["to"], [peer("istio-system", expression={
            "key": "istio", "operator": "In",
            "values": ["ingressgateway", "octelium-api-ingressgateway"],
        })])
        dataplane = next(rule for rule in egress if rule["ports"] == [
            {"protocol": "TCP", "port": 8080}])
        self.assertEqual(dataplane["to"], [peer("octelium", labels={
            "app": "octelium",
            "octelium.com/component": "ingress-dataplane",
            "octelium.com/component-type": "cluster",
        })])

        config = nested_yaml(documents(APPS / "octelium-public/configmap.yaml")[0]
                             ["data"]["config.yaml"])
        origins = {urlparse(route["service"]).netloc for route in config["ingress"]
                   if not route["service"].startswith("http_status:")}
        self.assertEqual(origins, {
            "istio-ingressgateway.istio-system.svc.cluster.local:443",
            "octelium-api-ingressgateway.istio-system.svc.cluster.local:443",
            "octelium-ingress-dataplane.octelium.svc.cluster.local:8080",
        })
        self.assertEqual(len([rule for rule in egress if rule["ports"] == [
            {"protocol": "TCP", "port": 443}]]), 1)
        self.assertEqual(len([rule for rule in egress if rule["ports"] == [
            {"protocol": "TCP", "port": 8080}]]), 1)
        self.assertEqual(documents(APPS / "istio/tailnet-gateway.yaml")[0]
                         ["spec"]["selector"], {"istio": "ingressgateway"})
        self.assertEqual(documents(APPS / "istio/octelium-api-gateway-values.yaml")[0]
                         ["labels"]["istio"], "octelium-api-ingressgateway")
        emergency = documents(APPS / "octelium-enterprise/emergency-dataplane.yaml")[0]
        self.assertEqual({key: emergency["spec"]["template"]["metadata"]["labels"][key]
                          for key in dataplane["to"][0]["podSelector"]["matchLabels"]},
                         dataplane["to"][0]["podSelector"]["matchLabels"])

    def test_harbor_metrics_accept_only_prometheus(self):
        monitor = peer("monitoring", labels={"app.kubernetes.io/name": "prometheus"})
        components = policy("harbor", "harbor-components")["ingress"][1]
        exporter = policy("harbor", "harbor-vulnerability-exporter")["ingress"][0]
        self.assertEqual(components, {"from": [monitor],
                                      "ports": [{"protocol": "TCP", "port": 8001}]})
        self.assertEqual(exporter, {"from": [monitor],
                                    "ports": [{"protocol": "TCP", "port": 8080}]})
        self.assertTrue(documents(APPS / "harbor/values.yaml")[0]
                        ["metrics"]["serviceMonitor"]["enabled"])
        vulnerability = next(item for item in documents(APPS / "harbor/vulnerability-exporter.yaml")
                             if item["kind"] == "ServiceMonitor")
        self.assertEqual(vulnerability["metadata"]["labels"]["release"], "prometheus")
        self.assertEqual(vulnerability["spec"]["endpoints"][0]["port"], "metrics")
        namespaces = documents(APPS / "prometheus/values.yaml")[0]["prometheus"]
        self.assertEqual(namespaces["prometheusSpec"]["serviceMonitorNamespaceSelector"]
                         ["matchExpressions"][0]["values"], ["monitoring", "harbor"])

    def test_harbor_and_mastodon_ingress_match_gateway_routes(self):
        gateway = peer("istio-system", labels={"istio": "ingressgateway"})
        harbor = policy("harbor", "harbor-nginx")["ingress"][0]
        self.assertIn(gateway, harbor["from"])
        self.assertEqual([source for source in harbor["from"] if
                          source.get("namespaceSelector", {}).get("matchLabels", {}).get(
                              "kubernetes.io/metadata.name") == "istio-system"], [gateway])
        self.assertEqual(harbor["ports"], [{"protocol": "TCP", "port": 8080}])
        mastodon = policy("mastodon", "mastodon-gateway-ingress")["ingress"][0]
        self.assertEqual(mastodon["from"], [gateway])
        self.assertEqual(mastodon["ports"], [
            {"protocol": "TCP", "port": 3000}, {"protocol": "TCP", "port": 4000},
            {"protocol": "TCP", "port": 15008}])
        namespace = documents(APPS / "mastodon/namespace.yaml")[0]["metadata"]["labels"]
        self.assertEqual(namespace["istio.io/dataplane-mode"], "ambient")
        for app in ("harbor", "mastodon"):
            route = documents(APPS / app / "virtualservice.yaml")[0]["spec"]
            self.assertEqual(route["gateways"], ["istio-system/tailnet-gateway"])
            destinations = {(backend["destination"]["host"],
                             backend["destination"]["port"]["number"])
                            for rule in route["http"] for backend in rule["route"]}
            self.assertEqual(destinations, {
                "harbor": {("harbor.harbor.svc.cluster.local", 80)},
                "mastodon": {("mastodon-web.mastodon.svc.cluster.local", 3000),
                             ("mastodon-streaming.mastodon.svc.cluster.local", 4000)},
            }[app])
        self.assertEqual(documents(APPS / "istio/tailnet-gateway.yaml")[0]
                         ["spec"]["selector"], gateway["podSelector"]["matchLabels"])


if __name__ == "__main__":
    unittest.main()
