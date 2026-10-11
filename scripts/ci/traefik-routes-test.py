#!/usr/bin/env python3
"""Offline inventory and access-boundary checks for the Traefik cutover."""
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
APPS = {
    "affine": "affine.affine:3010",
    "argocd": "argocd-server.argocd:80",
    "bazarr": "bazarr.media:6767",
    "compass": "compass.monitoring:8080",
    "deluge": "deluge.media:8112",
    "dispatcharr": "dispatcharr.media:9191",
    "fleet": "fleet.fleet:8080",
    "grafana": "grafana.monitoring:80",
    "harbor": "harbor.harbor:80",
    "kiali": "kiali.monitoring:20001",
    "langfuse": "langfuse-web.langfuse:3000",
    "litellm": "litellm.ai:4000",
    "multica": "multica-frontend.ai:3000",
    "n8n": "n8n.automation:5678",
    "nofx": "nofx-frontend.nofx:80",
    "octobot": "octobot.finance:5001",
    "openclaw": "openclaw.ai:8080",
    "policy-bot": "policy-bot.automation:8080",
    "prowlarr": "prowlarr.media:9696",
    "radarr": "radarr.media:7878",
    "sonarr": "sonarr.media:8989",
}


NODE_REGISTRY_SOURCES = [
    "10.1.0.199/32", "10.1.0.200/32", "10.1.0.201/32", "10.1.0.202/32",
    "10.244.1.1/32", "10.244.2.1/32", "10.244.3.1/32", "10.244.4.1/32",
    "10.244.1.0/32", "10.244.2.0/32", "10.244.3.0/32", "10.244.4.0/32",
]


def read_yaml(relative):
    return json.loads(subprocess.check_output(
        ["yq", "-o=json", ".", str(ROOT / relative)], text=True))


HTTP = read_yaml("clusters/homelab/apps/traefik/routes.yaml")["http"]
ROUTERS = HTTP["routers"]


class RouteTests(unittest.TestCase):
    def test_complete_private_inventory_and_direct_backends(self):
        controls = {"cordium", "octelium-cluster", "octelium-alias",
                    "octelium-api", "octelium-console"}
        self.assertEqual(set(ROUTERS), set(APPS) | controls |
                         {"n8n-webhook", "policy-bot-hook", "harbor-registry"})
        for app, backend in APPS.items():
            with self.subTest(app=app):
                router = ROUTERS[app]
                self.assertEqual(router["entryPoints"], ["websecure"])
                self.assertEqual(router["tls"], {})
                self.assertEqual(router["service"], app)
                host = f"Host(`{app}.stinkyboi.com`)"
                if app != "fleet":
                    self.assertEqual(router["rule"], host)
                service, port = backend.split(":")
                self.assertEqual(HTTP["services"][app]["loadBalancer"], {
                    "servers": [{"url": f"http://{service}.svc.cluster.local:{port}"}]})
        for name in controls:
            self.assertEqual(ROUTERS[name]["entryPoints"], ["websecure"])
            self.assertEqual(ROUTERS[name]["tls"], {})

    def test_fleet_setup_has_no_router(self):
        rule = ROUTERS["fleet"]["rule"]
        self.assertEqual(rule, "Host(`fleet.stinkyboi.com`) && "
                         "!PathRegexp(`^/(api/(v1/)?)?setup(/|$)`)")
        self.assertEqual(ROUTERS["fleet"]["middlewares"], ["reject-ambiguous-paths"])
        self.assertEqual(HTTP["middlewares"]["reject-ambiguous-paths"],
                         {"encodedCharacters": {"allowEncodedSlash": False}})
        blocked = re.compile(re.search(r"PathRegexp\(`(.*)`\)", rule)[1])
        for base in ("/setup", "/api/setup", "/api/v1/setup"):
            for suffix in ("", "/", "/anything"):
                self.assertIsNotNone(blocked.search(base + suffix))
        for path in ("/", "/login", "/api/v1/fleet", "/mdm/apple/mdm",
                     "/api/v1/osquery/enroll"):
            self.assertIsNone(blocked.search(path))
        # An alternate Fleet router would bypass the setup exclusions.
        self.assertEqual([name for name, route in ROUTERS.items()
                          if "fleet.stinkyboi.com" in route["rule"]], ["fleet"])

    def test_funnel_is_only_the_reviewed_callbacks(self):
        public = {name: route for name, route in ROUTERS.items()
                  if "funnel" in route["entryPoints"]}
        self.assertEqual(set(public), {"n8n-webhook", "policy-bot-hook"})
        expected = {
            "n8n-webhook": ("n8n", "PathRegexp(`^/(webhook|webhook-test|webhook-waiting)(/|$)`)"),
            "policy-bot-hook": ("policy-bot", "Path(`/api/github/hook`)"),
        }
        for name, (service, paths) in expected.items():
            self.assertEqual(public[name], {
                "entryPoints": ["funnel"],
                "rule": f"Host(`{name}.tail67beb.ts.net`) && {paths}",
                "middlewares": ["reject-ambiguous-paths"],
                "service": service,
            })
        allowed = re.compile(re.search(r"PathRegexp\(`(.*)`\)",
                                       public["n8n-webhook"]["rule"])[1])
        for base in ("/webhook", "/webhook-test", "/webhook-waiting"):
            for suffix in ("", "/", "/workflow-id"):
                self.assertIsNotNone(allowed.search(base + suffix))
        for path in ("/", "/rest/settings", "/rest/login", "/healthz",
                     "/webhook-admin", "/webhook-test-admin", "/webhook-waiting-admin"):
            self.assertIsNone(allowed.search(path))

    def test_cordium_and_control_plane_preserve_hosts_and_protocols(self):
        self.assertEqual(ROUTERS["cordium"]["rule"],
                         r"Host(`cordium.stinkyboi.com`) || HostRegexp(`^[^.]+\.cordium\.stinkyboi\.com$`)")
        self.assertEqual(ROUTERS["octelium-cluster"]["rule"],
                         "Host(`stinkyboi.com`) || Host(`portal.stinkyboi.com`)")
        self.assertEqual(ROUTERS["octelium-api"]["rule"], "Host(`octelium-api.stinkyboi.com`)")
        self.assertEqual(HTTP["services"]["octelium-api"]["loadBalancer"]["servers"],
                         [{"url": "h2c://octelium-ingress-dataplane.octelium.svc.cluster.local:8080"}])
        for name, backend in {
            "cordium": "svc-default-cordium",
            "octelium-cluster": "octelium-ingress-dataplane",
        }.items():
            self.assertEqual(HTTP["services"][name]["loadBalancer"]["servers"],
                             [{"url": f"http://{backend}.octelium.svc.cluster.local:8080"}])
        self.assertEqual(ROUTERS["octelium-console"]["rule"], "Host(`console.stinkyboi.com`)")
        self.assertEqual(HTTP["services"]["octelium-console"]["loadBalancer"], {
            "serversTransport": "octelium-console",
            "servers": [{"url": "https://istio-ingressgateway.istio-system.svc.cluster.local:443"}],
        })
        self.assertEqual(HTTP["serversTransports"], {
            "octelium-console": {"serverName": "console.stinkyboi.com"},
        })
        self.assertEqual(ROUTERS["octelium-alias"]["rule"], "Host(`octelium.stinkyboi.com`)")
        self.assertEqual(ROUTERS["octelium-alias"]["middlewares"], ["octelium-canonical-host"])
        self.assertEqual(HTTP["middlewares"]["octelium-canonical-host"]["headers"],
                         {"customRequestHeaders": {"Host": "stinkyboi.com"}})
        self.assertEqual({route["service"] for route in ROUTERS.values()},
                         set(HTTP["services"]))

    def test_hbone_cannot_bypass_the_ingress_network_policy(self):
        policy = read_yaml("clusters/homelab/apps/traefik/authorizationpolicy.yaml")["spec"]
        self.assertEqual(policy["action"], "ALLOW")
        self.assertEqual(policy["rules"], [
            {"from": [{"source": {"notPrincipals": ["*"]}}],
             "to": [{"operation": {"ports": ["8000", "8080", "8443"]}}]},
            {"from": [{"source": {"principals": [
                "cluster.local/ns/octelium-client/sa/octelium-client"]}}],
             "to": [{"operation": {"ports": ["8443"]}}]},
            {"from": [{"source": {"notPrincipals": ["*"],
                                    "ipBlocks": NODE_REGISTRY_SOURCES}}],
             "to": [{"operation": {"ports": ["9443"]}}]},
            {"to": [{"operation": {"ports": ["9000"]}}]},
        ])

    def test_retained_connector_is_scoped_to_its_identity_and_private_tls(self):
        policy = read_yaml("clusters/homelab/apps/traefik/authorizationpolicy.yaml")["spec"]
        authenticated = {
            (principal, port)
            for rule in policy["rules"]
            for peer in rule.get("from", [])
            for principal in peer["source"].get("principals", [])
            for target in rule["to"]
            for port in target["operation"]["ports"]
        }
        principal = "cluster.local/ns/octelium-client/sa/octelium-client"
        self.assertEqual(authenticated, {(principal, "8443")})
        for identity, port in (
            ("cluster.local/ns/octelium-client/sa/default", "8443"),
            ("cluster.local/ns/default/sa/octelium-client", "8443"),
            (principal, "8000"), (principal, "8080"), (principal, "9443"),
        ):
            self.assertNotIn((identity, port), authenticated)
        network = read_yaml("clusters/homelab/apps/traefik/networkpolicy.yaml")["spec"]
        connector, = [rule for rule in network["ingress"] if any(
            peer.get("namespaceSelector", {}).get("matchLabels", {}).get(
                "kubernetes.io/metadata.name") == "octelium-client"
            for peer in rule.get("from", []))]
        self.assertEqual(connector, {
            "from": [{
                "namespaceSelector": {"matchLabels": {
                    "kubernetes.io/metadata.name": "octelium-client"}},
                "podSelector": {"matchLabels": {
                    "app.kubernetes.io/name": "octelium",
                    "app.kubernetes.io/instance": "octelium-client"}},
            }],
            "ports": [{"protocol": "TCP", "port": 8443}],
        })

    def test_ambient_app_policies_separate_hbone_from_cleartext_sources(self):
        for app, name, port in (("affine", "affine-server", 3010),
                                ("nofx", "nofx-frontend", 80),
                                ("openclaw", "openclaw", 8080),
                                ("policy-bot", "policy-bot", 8080)):
            with self.subTest(app=app):
                policies = json.loads(subprocess.check_output([
                    "yq", "ea", "-o=json", "[.]",
                    str(ROOT / f"clusters/homelab/apps/{app}/networkpolicy.yaml")], text=True))
                policy, = [item for item in policies if item["metadata"]["name"] == name]
                ingress = policy["spec"]["ingress"]
                self.assertEqual([rule for rule in ingress if not rule.get("from")],
                                 [{"ports": [{"protocol": "TCP", "port": 15008}]}])
                cleartext, = [rule for rule in ingress if rule.get("from")]
                self.assertEqual(cleartext["ports"], [{"protocol": "TCP", "port": port}])
                self.assertIn({
                    "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "traefik"}},
                    "podSelector": {"matchLabels": {"app.kubernetes.io/name": "traefik"}},
                }, cleartext["from"])

    def test_node_registry_sources_are_exact_hosts_bridges_and_overlays(self):
        policy = read_yaml("clusters/homelab/apps/traefik/networkpolicy.yaml")["spec"]
        registry, = [rule for rule in policy["ingress"]
                     if {"protocol": "TCP", "port": 9443} in rule["ports"]]
        self.assertEqual(registry, {
            "from": [{"ipBlock": {"cidr": source}} for source in NODE_REGISTRY_SOURCES],
            "ports": [{"protocol": "TCP", "port": 9443}],
        })
        # A nearby LAN host or ordinary Pod must not match this source boundary.
        networks = [ipaddress.ip_network(source["ipBlock"]["cidr"])
                    for source in registry["from"]]
        for address in ("10.244.1.0", "10.244.2.0", "10.244.3.0", "10.244.4.0"):
            self.assertTrue(any(ipaddress.ip_address(address) in net for net in networks))
        for address in ("10.1.0.198", "10.1.0.203", "10.244.1.2", "10.244.2.2",
                        "10.244.3.2", "10.244.4.2"):
            self.assertFalse(any(ipaddress.ip_address(address) in net for net in networks))

    def test_node_registry_has_no_dashboard_or_other_app_route(self):
        registry = {name: route for name, route in ROUTERS.items()
                    if "registry" in route["entryPoints"]}
        self.assertEqual(registry, {"harbor-registry": {
            "entryPoints": ["registry"],
            "rule": "Host(`harbor.stinkyboi.com`) && "
                    "(Path(`/v2`) || PathPrefix(`/v2/`) || Path(`/service/token`))",
            "middlewares": ["reject-ambiguous-paths"],
            "service": "harbor", "tls": {},
        }})


if __name__ == "__main__":
    unittest.main()
