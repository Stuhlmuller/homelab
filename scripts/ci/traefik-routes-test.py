#!/usr/bin/env python3
"""Offline inventory and access-boundary checks for the Traefik cutover."""
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
            {"from": [{"source": {"notPrincipals": ["*"], "ipBlocks": [
                "10.1.0.199/32", "10.1.0.200/32", "10.1.0.201/32", "10.1.0.202/32"]}}],
             "to": [{"operation": {"ports": ["9443"]}}]},
            {"to": [{"operation": {"ports": ["9000"]}}]},
        ])

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
