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
            / "terraform/live/homelab/variables/traefik/cf_dns_api_token/terragrunt.hcl",
        ]
        for unit in secret_units:
            content = unit.read_text()
            self.assertIn("ssm_parameters =", content, unit.name)
            self.assertNotIn("replace-me", content, unit.name)
            self.assertNotIn("dokploy_secure_password", content, unit.name)

    def test_tailscale_bootstrap_reads_auth_key_from_ssm(self) -> None:
        inventory = (
            ROOT / "ansible/inventories/production/group_vars/all.yml"
        ).read_text()
        role = (ROOT / "ansible/roles/tailscale/tasks/main.yml").read_text()

        self.assertIn("tailscale_auth_ssm_parameter:", inventory)
        self.assertNotIn("tailscale_auth_key:", inventory)
        self.assertIn("aws", role)
        self.assertIn("get-parameter", role)
        self.assertIn("become: false", role)
        self.assertIn("'tailscale', 'up', '--reset'", role)
        self.assertIn("HaveNodeKey", role)
        self.assertIn("NeedsLogin", role)
        self.assertIn("tailscale_requires_authkey", role)
        self.assertIn("tailscale_auth_key_value", role)
        self.assertIn("tailscale_up_argv", role)

    def test_readme_documents_ssm_secret_sources(self) -> None:
        content = (ROOT / "README.md").read_text()
        self.assertIn("AWS SSM Parameter Store", content)
        self.assertIn("/homelab/dokploy/postgres_password", content)
        self.assertIn("/homelab/paperclip/better_auth_secret", content)
        self.assertNotIn("/homelab/traefik/ts_authkey", content)

    def test_github_workflows_fetch_tailscale_auth_key_from_ssm(self) -> None:
        plan = (ROOT / ".github/workflows/plan.yml").read_text()
        deploy = (ROOT / ".github/workflows/deploy.yml").read_text()
        action = (ROOT / ".github/actions/setup-infrastructure/action.yml").read_text()

        self.assertNotIn("secrets.TS_AUTH_KEY", plan)
        self.assertNotIn("secrets.TS_AUTH_KEY", deploy)
        self.assertIn("TAILSCALE_AUTH_KEY_SSM_PARAMETER", plan)
        self.assertIn("TAILSCALE_AUTH_KEY_SSM_PARAMETER", deploy)
        self.assertIn("aws-actions/configure-aws-credentials@", plan)
        self.assertIn("aws-actions/configure-aws-credentials@", deploy)
        self.assertIn("aws ssm get-parameter", action)
        self.assertIn("tailscale set --accept-routes=true", action)
        self.assertIn("connectivity-probe-address: 10.1.0.200", plan)
        self.assertIn("connectivity-probe-address: 10.1.0.200", deploy)
        self.assertIn("ping: ${{ inputs.tailscale-ping-hosts }}", action)
        self.assertIn("tailscale-ping-hosts: homelab-vpn", plan)
        self.assertIn("tailscale-ping-hosts: homelab-vpn", deploy)
