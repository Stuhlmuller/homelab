#!/usr/bin/env python3
"""Keep Mastodon's public route away from private apps and datastores."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/mastodon"


def documents(name):
    return json.loads(subprocess.check_output([
        "yq", "eval-all", "-o=json", ". as $doc ireduce ([]; . + [$doc])",
        str(APP / name),
    ], text=True))


class Routes(unittest.TestCase):
    def test_public_egress_matches_configured_smtp_port(self):
        config = documents("configmap.yaml")[0]["data"][".env.production"]
        entries = dict(line.split("=", 1) for line in config.splitlines() if "=" in line)
        federation = next(resource["spec"] for resource in documents("networkpolicy.yaml")
                          if resource["metadata"]["name"] == "mastodon-federation-egress")
        self.assertEqual(federation["podSelector"]["matchExpressions"][0]["values"],
                         ["mastodon-web", "mastodon-sidekiq"])
        self.assertEqual(len(federation["egress"]), 1)
        allowed = {(port["protocol"], port["port"])
                   for port in federation["egress"][0]["ports"]}
        self.assertEqual(allowed, {("TCP", 80), ("TCP", 443),
                                   ("TCP", int(entries["SMTP_PORT"]))})

    def test_public_route_only_reaches_mastodon(self):
        spec = documents("virtualservice.yaml")[0]["spec"]
        self.assertEqual(spec["hosts"], ["mastodon.stinkyboi.com"])
        self.assertEqual(spec["gateways"], ["istio-system/tailnet-gateway"])
        streaming, web = spec["http"]
        self.assertEqual(streaming["match"], [
            {"uri": {"exact": "/api/v1/streaming"}},
            {"uri": {"prefix": "/api/v1/streaming/"}},
        ])
        for route, service, port in [
            (streaming, "mastodon-streaming", 4000), (web, "mastodon-web", 3000),
        ]:
            self.assertEqual(route["route"], [{"destination": {
                "host": f"{service}.mastodon.svc.cluster.local", "port": {"number": port},
            }}])
        self.assertNotIn("match", web)

    def test_streaming_trust_avoids_unsafe_ipv6_subnets(self):
        environment = documents("configmap.yaml")[0]["data"]["streaming.env"]
        entries = dict(line.split("=", 1) for line in environment.splitlines() if "=" in line)
        self.assertEqual(entries["TRUSTED_PROXY_IP"], "loopback,uniquelocal")

    def test_cold_start_dependencies_precede_postgres(self):
        postgres = documents("postgres.yaml")[1]
        postgres_wave = int(postgres["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"])
        for name in ("serviceaccount.yaml", "externalsecret.yaml", "initdb-configmap.yaml", "storage.yaml"):
            for dependency in documents(name):
                wave = dependency["metadata"].get("annotations", {}).get("argocd.argoproj.io/sync-wave", "0")
                with self.subTest(resource=dependency["metadata"]["name"]):
                    self.assertLess(int(wave), postgres_wave)

    def test_application_credentials_and_native_image_user(self):
        for name in ("workloads.yaml", "migration.yaml", "bootstrap-job.yaml"):
            for resource in documents(name):
                if resource["kind"] not in ("Deployment", "Job"):
                    continue
                context = resource["spec"]["template"]["spec"]["securityContext"]
                self.assertEqual(context["runAsUser"], 991)
                self.assertEqual(context["runAsGroup"], 991)
                self.assertEqual(context["fsGroup"], 65534)
        postgres = documents("postgres.yaml")[1]
        role = documents("database-role-job.yaml")[0]
        self.assertLess(int(postgres["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]),
                        int(role["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]))
        runtime = documents("runtime-externalsecret.yaml")[0]["spec"]
        self.assertEqual(runtime["target"]["template"]["data"]["runtime-v2"], "ready")
        migration = documents("migration.yaml")[0]["spec"]["template"]["spec"]
        projection = next(v["secret"] for v in migration["volumes"] if v["name"] == "runtime")
        self.assertEqual(projection["secretName"], runtime["target"]["name"])
        self.assertFalse(projection.get("optional", False))
        self.assertEqual({item["key"] for item in projection["items"]}, {
            "runtime-v2", ".env.production", "vapid.pem", "smtp-password",
        })
        paths = {item["remoteRef"]["key"] for item in runtime["data"]}
        self.assertIn("/homelab/mastodon/postgres-app-password", paths)
        self.assertNotIn("/homelab/mastodon/postgres-password", paths)
        for environment in documents("configmap.yaml")[0]["data"].values():
            self.assertIn("DB_USER=mastodon_app\n", environment)
            self.assertIn("DB_PASS={{ .postgres_app_password }}", environment)
        redis = documents("redis.yaml")[1]["spec"]["template"]["spec"]
        auth = next(v["secret"] for v in redis["volumes"] if v["name"] == "auth")
        self.assertEqual(auth["items"], [{"key": "REDIS_PASSWORD", "path": "REDIS_PASSWORD"}])

    def test_gateway_cannot_reach_datastore_ports(self):
        peer, default, allowed = documents("authorizationpolicy.yaml")
        self.assertEqual(peer["spec"]["mtls"]["mode"], "STRICT")
        self.assertEqual(default["spec"], {})
        gateway, workload = allowed["spec"]["rules"]
        self.assertEqual(gateway["from"], [{"source": {"principals": [
            "cluster.local/ns/istio-system/sa/istio-ingressgateway",
        ]}}])
        self.assertEqual(gateway["to"], [{"operation": {"ports": ["3000", "4000"]}}])
        self.assertEqual(workload["from"], [{"source": {"principals": [
            "cluster.local/ns/mastodon/sa/mastodon",
        ]}}])


if __name__ == "__main__":
    unittest.main()
