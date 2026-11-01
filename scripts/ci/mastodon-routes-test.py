#!/usr/bin/env python3
"""Keep Mastodon's public route away from private apps and datastores."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/mastodon"


def documents(name):
    return json.loads(subprocess.check_output([
        "yq", "eval-all", "-o=json", ". as $doc ireduce ([]; . + [$doc])",
        str(APP / name),
    ], text=True))


class Routes(unittest.TestCase):
    def test_tunnel_only_bypasses_human_access_for_federation(self):
        configmap = ROOT / "clusters/homelab/apps/octelium-public/configmap.yaml"
        config = subprocess.check_output(["yq", "-r", '.data["config.yaml"]', str(configmap)], text=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(config)
            subprocess.run(["cloudflared", "tunnel", "--config", str(path), "ingress", "validate"],
                           check=True, capture_output=True, text=True)
            public = [
                "/.well-known/webfinger?resource=acct:rodman@mastodon.stinkyboi.com",
                "/.well-known/host-meta", "/actor", "/actor/inbox", "/actor/outbox", "/inbox",
                "/ap/users/117500824684615471", "/ap/users/123/inbox",
                "/ap/users/123/statuses/456", "/ap/users/123/collections/456",
                "/ap/users/123/quote_authorizations/456", "/users/rodman/inbox",
                "/users/rodman/collections/featured", "/contexts/123-456/items", "/collections/123",
                "/emojis/123", "/system/media_attachments/files/123/456/original/abc123.png",
                "/system/media_attachments/thumbnails/123/456/original/abc123.jpg",
                "/system/accounts/avatars/123/456/original/abc123.png",
                "/system/custom_emojis/images/123/456/static/abc123.png",
            ]
            private = [
                "/", "/home", "/admin", "/admin/accounts", "/auth/sign_in", "/auth/sign_up",
                "/oauth/authorize", "/oauth/token", "/settings", "/sidekiq", "/pghero",
                "/api/v1/accounts/verify_credentials", "/api/v2/instance", "/api/v1/streaming",
                "/api/v1/streaming/", "/@rodman", "/@rodman/123", "/assets/app.js",
                "/.well-known/nodeinfo", "/nodeinfo/2.0", "/media_proxy/123/x", "/backups/123/download",
                "/ap/../admin", "/ap/%2e%2e/admin", "/ap/%252e%252e/admin",
                "/users/rodman/../../admin", "/users/rodman/%2e%2e/%2e%2e/admin",
                "/ap/%2f..%2fadmin", "/ap/%5c..%5cadmin", "/ap/123;../../admin",
                "/system/media_attachments/files/123/original/../../../../admin",
                "/inbox/admin", "/inbox.json", "/.well-known/webfinger/../../admin",
            ]
            for uri, origin in [(uri, "https://istio-ingressgateway.") for uri in public] + [
                    (uri, "http://octelium-ingress-dataplane.") for uri in private]:
                with self.subTest(uri=uri):
                    result = subprocess.check_output([
                        "cloudflared", "tunnel", "--config", str(path), "ingress", "rule",
                        "https://mastodon.stinkyboi.com" + uri,
                    ], text=True, stderr=subprocess.STDOUT)
                    self.assertIn("service: " + origin, result)

    def test_private_client_service_requires_human_access(self):
        catalog = json.loads(subprocess.check_output([
            "yq", "ea", "-o=json", ". as $doc ireduce ([]; . + [$doc])",
            str(ROOT / "docs/examples/octelium/homelab-services.yaml"),
        ], text=True))
        service, = [r for r in catalog if r.get("kind") == "Service"
                    and r["metadata"]["name"] == "mastodon"]
        spec = service["spec"]
        self.assertEqual((spec["mode"], spec["port"]), ("WEB", 80))
        self.assertTrue(spec["isPublic"])
        self.assertFalse(spec["isAnonymous"])
        self.assertEqual(spec["authorization"]["policies"], ["homelab-human-web-access"])
        self.assertEqual(spec["config"]["upstream"]["url"],
                         "https://istio-ingressgateway.istio-system.svc.cluster.local:443")
        header = spec["config"]["http"]["header"]
        self.assertEqual(header["host"]["value"], "mastodon.stinkyboi.com")
        self.assertEqual(header["authorizationMode"], "PASS")
        self.assertEqual(header["forwardedMode"], "TRANSPARENT")

    def test_fresh_bootstrap_creates_backup_before_verification(self):
        rendered = subprocess.check_output(["kubectl", "kustomize", str(APP)], text=True)
        resources = json.loads(subprocess.check_output([
            "yq", "eval-all", "-o=json", ". as $doc ireduce ([]; . + [$doc])", "-",
        ], input=rendered, text=True))
        by_name = {r["metadata"]["name"]: r for r in resources}
        backup = by_name["mastodon-initial-backup-v1"]
        verify = by_name["mastodon-restore-verification-v2"]
        scheduled = by_name["mastodon-restore-verification"]
        self.assertEqual(verify["spec"], scheduled["spec"]["jobTemplate"]["spec"])
        self.assertEqual(scheduled["spec"]["schedule"], "35 3 * * *")
        self.assertEqual(scheduled["spec"]["timeZone"], "America/Los_Angeles")
        self.assertFalse(scheduled["spec"]["suspend"])
        self.assertEqual(scheduled["spec"]["concurrencyPolicy"], "Forbid")
        self.assertEqual(backup["spec"], by_name["mastodon-backup"]["spec"]["jobTemplate"]["spec"])
        for source, rendered_job in (("initial-backup-job.yaml", backup), ("restore-verification-job.yaml", verify)):
            source_pod = documents(source)[0]["spec"]["template"]["spec"]
            for key, value in source_pod.items():
                self.assertEqual(value, rendered_job["spec"]["template"]["spec"][key])
        def wave(resource):
            return int(resource["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"])
        self.assertLess(wave(documents("bootstrap-job.yaml")[0]), wave(backup))
        self.assertLess(wave(backup), wave(verify))

    def test_restore_failure_cannot_report_success(self):
        script = documents("restore-verification-cronjob.yaml")[0]["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["args"][0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "restore").mkdir()
            backup = root / "backup/database/20261025T100000Z"
            backup.mkdir(parents=True)
            (backup / "SHA256SUMS").write_text("")
            binaries = root / "bin"
            binaries.mkdir()
            for name in ("sha256sum", "initdb", "pg_ctl", "createdb", "psql", "pg_restore"):
                path = binaries / name
                path.write_text("#!/bin/sh\n" + ("exit 1\n" if name == "pg_restore" else "echo t\n"))
                path.chmod(0o700)
            script = script.replace("/restore", str(root / "restore")).replace("/backup", str(root / "backup"))
            result = subprocess.run(["/bin/sh", "-ec", script], text=True, capture_output=True,
                                    env={**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"]})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("restore failed", result.stderr)
            self.assertNotIn("catalog verified", result.stdout)

    def test_restore_cannot_mount_production_database_or_credentials(self):
        cron = documents("restore-verification-cronjob.yaml")[0]
        job = cron["spec"]["jobTemplate"]
        pod = job["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        claims = [v["persistentVolumeClaim"] for v in pod["volumes"] if "persistentVolumeClaim" in v]
        self.assertEqual(claims, [{"claimName": "mastodon-backup", "readOnly": True}])
        self.assertFalse(any("secret" in v for v in pod["volumes"]))
        self.assertEqual(job["spec"]["backoffLimit"], 0)
        self.assertEqual(int(cron["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]), 4)
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
