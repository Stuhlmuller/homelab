from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class NomadJobTests(unittest.TestCase):
    def test_service_jobs_have_traefik_or_health_checks(self) -> None:
        for job_file in (ROOT / "nomad" / "jobs").glob("*/job.nomad.hcl"):
            content = job_file.read_text()
            if 'type        = "service"' not in content:
                continue
            self.assertIn("service {", content, job_file.name)
            self.assertIn("check {", content, job_file.name)

    def test_traefik_job_uses_consul_catalog_and_tls(self) -> None:
        content = (ROOT / "nomad" / "jobs" / "traefik" / "job.nomad.hcl").read_text()
        self.assertIn("[providers.consulCatalog]", content)
        self.assertIn("[providers.file]", content)
        self.assertIn("certResolver = \"letsencrypt\"", content)
        self.assertIn("static = 80", content)
        self.assertIn("static = 443", content)
        self.assertIn("api@internal", content)
        self.assertIn("insecure  = false", content)
        self.assertIn("CF_DNS_API_TOKEN_FILE", content)
        self.assertIn("nomad.stinkyboi.com", content)
        self.assertIn("consul.stinkyboi.com", content)
        self.assertIn("nomad-ui", content)
        self.assertIn("consul-ui", content)
        self.assertIn("{{- .cf_dns_api_token.Value | trimSpace -}}", content)
        self.assertNotIn("CF_DNS_API_TOKEN={{", content)

    def test_dokploy_job_routes_through_traefik(self) -> None:
        content = (ROOT / "nomad" / "jobs" / "dokploy" / "job.nomad.hcl").read_text()
        self.assertIn("traefik.http.routers.dokploy.rule", content)
        self.assertIn("traefik.http.routers.dokploy.entrypoints=websecure", content)
        self.assertIn('mode = "bridge"', content)
        self.assertIn("nomad/jobs/dokploy/config", content)
        self.assertIn("POSTGRES_PASSWORD_FILE", content)
        self.assertIn("uid         = 65534", content)
        self.assertIn("gid         = 65534", content)
        self.assertIn('POSTGRES_HOST           = "127.0.0.1"', content)
        self.assertNotIn("loadbalancer.server.port=3000", content)
        self.assertNotIn("DATABASE_URL=", content)
        self.assertNotIn("POSTGRES_PASSWORD={{", content)

    def test_paperclip_job_routes_through_traefik_with_file_backed_config(self) -> None:
        content = (ROOT / "nomad" / "jobs" / "paperclip" / "job.nomad.hcl").read_text()
        self.assertIn('default = "nomad-primary"', content)
        self.assertIn('attribute = "${node.unique.name}"', content)
        self.assertIn("value     = var.paperclip_nomad_node_name", content)
        self.assertIn("ghcr.io/paperclipai/paperclip:latest", content)
        self.assertIn('image = "postgres:17-alpine"', content)
        self.assertIn("traefik.http.routers.paperclip.rule", content)
        self.assertIn("traefik.http.routers.paperclip.entrypoints=websecure", content)
        self.assertIn('mode = "bridge"', content)
        self.assertIn("nomad/jobs/paperclip/config", content)
        self.assertIn('destination = "secrets/postgres_password"', content)
        self.assertIn('POSTGRES_PASSWORD_FILE = "${NOMAD_SECRETS_DIR}/postgres_password"', content)
        self.assertIn('destination = "secrets/paperclip-runtime.env"', content)
        self.assertIn('DATABASE_URL="postgres://paperclip:{{ .postgres_password.Value | trimSpace }}@127.0.0.1:5432/paperclip"', content)
        self.assertIn('PAPERCLIP_CONFIG = "/paperclip/instances/default/config.json"', content)
        self.assertIn('PAPERCLIP_HOME   = "/paperclip"', content)
        self.assertIn('BETTER_AUTH_SECRET="{{ .better_auth_secret.Value }}"', content)
        self.assertIn('Host = ["paperclip.stinkyboi.com"]', content)

    def test_policy_bot_job_uses_tailscale_funnel_with_file_backed_config(self) -> None:
        content = (ROOT / "nomad" / "jobs" / "policy-bot" / "job.nomad.hcl").read_text()
        self.assertIn("palantirtechnologies/policy-bot:1.41.1", content)
        self.assertIn('default = "nomad-primary"', content)
        self.assertIn('attribute = "${node.unique.name}"', content)
        self.assertIn("value     = var.policy_bot_nomad_node_name", content)
        self.assertIn('mode = "bridge"', content)
        self.assertIn("static = 18080", content)
        self.assertIn("nomad/jobs/policy-bot", content)
        self.assertIn('destination = "secrets/policy-bot.yml"', content)
        self.assertIn('"${NOMAD_SECRETS_DIR}/policy-bot.yml"', content)
        self.assertIn('path     = "/api/health"', content)
        self.assertIn("github_app_private_key", content)
        self.assertNotIn("traefik.http.routers.policy-bot.rule", content)
