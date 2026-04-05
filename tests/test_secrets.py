from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class SecretManagementTests(unittest.TestCase):
    def test_live_secret_units_reference_ssm_parameter_names(self) -> None:
        secret_units = [
            ROOT
            / "terraform/live/homelab/variables/dokploy/config/terragrunt.hcl",
            ROOT
            / "terraform/live/homelab/variables/paperclip/config/terragrunt.hcl",
            ROOT
            / "terraform/live/homelab/variables/policy-bot/config/terragrunt.hcl",
            ROOT
            / "terraform/live/homelab/variables/traefik/cf_dns_api_token/terragrunt.hcl",
        ]
        for unit in secret_units:
            content = unit.read_text()
            self.assertIn("ssm_parameters =", content, unit.name)
            self.assertNotIn("replace-me", content, unit.name)
            self.assertNotIn("dokploy_secure_password", content, unit.name)

    def test_tailscale_bootstrap_requires_existing_node_state(self) -> None:
        inventory = (
            ROOT / "ansible/inventories/production/group_vars/all.yml"
        ).read_text()
        role = (ROOT / "ansible/roles/tailscale/tasks/main.yml").read_text()

        self.assertNotIn("tailscale_auth_ssm_parameter:", inventory)
        self.assertNotIn("tailscale_auth_key:", inventory)
        self.assertNotIn("get-parameter", role)
        self.assertNotIn("--authkey=", role)
        self.assertIn("'tailscale', 'up', '--reset'", role)
        self.assertIn("HaveNodeKey", role)
        self.assertIn("Complete `tailscale up` manually on the host", role)
        self.assertIn("reusable node key", role)
        self.assertIn("tailscale_up_argv", role)

    def test_readme_documents_ssm_secret_sources(self) -> None:
        content = (ROOT / "README.md").read_text()
        self.assertIn("AWS SSM Parameter Store", content)
        self.assertIn("/homelab/dokploy/postgres_password", content)
        self.assertIn("/homelab/paperclip/better_auth_secret", content)
        self.assertIn("/homelab/policy-bot/github_app_integration_id", content)
        self.assertIn("/homelab/policy-bot/github_app_private_key", content)
        self.assertNotIn("/homelab/tailscale/auth_key", content)
        self.assertNotIn("/homelab/traefik/ts_authkey", content)

    def test_github_workflows_prefer_tailscale_oauth_and_support_authkey_fallback(self) -> None:
        plan = (ROOT / ".github/workflows/plan.yml").read_text()
        deploy = (ROOT / ".github/workflows/deploy.yml").read_text()
        action = (ROOT / ".github/actions/setup-infrastructure/action.yml").read_text()

        self.assertIn("secrets.TS_AUTH_KEY", plan)
        self.assertIn("secrets.TS_AUTH_KEY", deploy)
        self.assertIn("secrets.TS_OAUTH_CLIENT_ID", plan)
        self.assertIn("secrets.TS_OAUTH_SECRET", plan)
        self.assertIn("secrets.TS_OAUTH_CLIENT_ID", deploy)
        self.assertIn("secrets.TS_OAUTH_SECRET", deploy)
        self.assertIn("vars.TAILSCALE_AUTH_KEY_SSM_PARAMETER", plan)
        self.assertIn("vars.TAILSCALE_AUTH_KEY_SSM_PARAMETER", deploy)
        self.assertIn("aws-actions/configure-aws-credentials@", plan)
        self.assertIn("aws-actions/configure-aws-credentials@", deploy)
        self.assertIn("tailscale-auth-key:", action)
        self.assertIn("oauth-client-id:", action)
        self.assertIn("oauth-secret:", action)
        self.assertIn("tailscale-auth-key-parameter:", action)
        self.assertIn("aws ssm get-parameter", action)
        self.assertIn("mode=oauth", action)
        self.assertIn("mode=authkey", action)
        self.assertIn("mode=authkey-parameter", action)
        self.assertIn("tailscale set --accept-routes=true", action)
        self.assertNotIn("connectivity-probe-address: 100.94.104.7", plan)
        self.assertIn("-refresh=false", plan)
        self.assertIn("connectivity-probe-address: 100.94.104.7", deploy)
