from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class LiveOpsTests(unittest.TestCase):
    def test_live_operation_scripts_exist(self) -> None:
        for relative in [
            "ansible/playbooks/reconcile-tailscale.yml",
            "scripts/bootstrap-rolling.sh",
            "scripts/validate-aws-kms.sh",
            "scripts/deploy-live.sh",
            "scripts/validate-aws-ssm.sh",
            "scripts/validate-live-cluster.sh",
            "scripts/validate-live-workloads.sh",
            "scripts/validate-shell.sh",
            "scripts/unlock-terragrunt-unit.sh",
        ]:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_terragrunt_units_define_live_dependencies(self) -> None:
        shared_data = (
            ROOT / "terraform/live/homelab/volumes/shared-data/terragrunt.hcl"
        ).read_text()
        traefik = (ROOT / "terraform/live/homelab/jobs/traefik/terragrunt.hcl").read_text()
        dokploy = (ROOT / "terraform/live/homelab/jobs/dokploy/terragrunt.hcl").read_text()
        paperclip = (ROOT / "terraform/live/homelab/jobs/paperclip/terragrunt.hcl").read_text()
        policy_bot = (ROOT / "terraform/live/homelab/jobs/policy-bot/terragrunt.hcl").read_text()

        self.assertIn("../../jobs/nfs-csi-plugin", shared_data)
        self.assertIn("../../variables/traefik/cf_dns_api_token", traefik)
        self.assertIn("../../volumes/shared-data", traefik)
        self.assertIn("../../variables/dokploy/config", dokploy)
        self.assertIn("../../volumes/shared-data", dokploy)
        self.assertIn("../../variables/paperclip/config", paperclip)
        self.assertIn("../../volumes/shared-data", paperclip)
        self.assertIn("../../variables/policy-bot/config", policy_bot)

    def test_makefile_exposes_live_targets(self) -> None:
        content = (ROOT / "Makefile").read_text()
        for target in [
            "bootstrap-rolling:",
            "reconcile-tailscale:",
            "validate-ssm:",
            "validate-kms:",
            "validate-live-cluster:",
            "validate-live-workloads:",
            "validate-live:",
            "unlock-state:",
            "deploy-live:",
        ]:
            self.assertIn(target, content)
        self.assertNotIn("run --all --graph", content)

    def test_ansible_validation_checks_controller_aws_sdk_dependencies(self) -> None:
        content = (ROOT / "scripts/validate-ansible.sh").read_text()
        self.assertIn("import boto3, botocore", content)
        self.assertIn("repository validation", content)

    def test_live_workload_validation_checks_tailscale_backend_state(self) -> None:
        content = (ROOT / "scripts/validate-live-workloads.sh").read_text()
        self.assertIn('tailscale status --json', content)
        self.assertIn('backend_state != "Running"', content)
        self.assertIn('ansible/inventories/production/hosts.yml', content)
        self.assertIn('job_status_file="$(mktemp)"', content)
        self.assertIn('tailscale_status_file="$(mktemp)"', content)
        self.assertIn('if isinstance(payload, list):', content)
        self.assertIn('running allocations', content)
        self.assertIn("nomad var get -item public_url", content)
        self.assertIn("tailscale funnel status", content)
        self.assertIn("paperclip.stinkyboi.com", content)
        self.assertIn("POLICY_BOT_LOCAL_TARGET", content)
        self.assertIn("POLICY_BOT_FUNNEL_AUTH_PATH", content)
        self.assertIn("POLICY_BOT_FUNNEL_HOOK_PATH", content)
        self.assertIn("|-- / proxy", content)

    def test_live_cluster_validation_prefers_ssh_when_ping_is_filtered(self) -> None:
        content = (ROOT / "scripts/validate-live-cluster.sh").read_text()
        self.assertIn('USE_TAILSCALE_ENDPOINTS="${USE_TAILSCALE_ENDPOINTS:-0}"', content)
        self.assertIn("ping failed; continuing with SSH validation", content)
        self.assertIn("host is reachable over SSH and core services are active", content)
        self.assertIn("tailscale_ip", content)
        self.assertIn("ssh -o BatchMode=yes", content)

    def test_live_workload_validation_can_use_tailscale_endpoints(self) -> None:
        content = (ROOT / "scripts/validate-live-workloads.sh").read_text()
        self.assertIn('USE_TAILSCALE_ENDPOINTS="${USE_TAILSCALE_ENDPOINTS:-0}"', content)
        self.assertIn("tailscale_ip", content)

    def test_tailscale_role_can_reconcile_funnel(self) -> None:
        content = (ROOT / "ansible" / "roles" / "tailscale" / "tasks" / "main.yml").read_text()
        self.assertIn("tailscale funnel status", content)
        self.assertIn("tailscale_funnel_mounts", content)
        self.assertIn("--set-path=", content)
        self.assertIn("--bg", content)
        self.assertIn("--yes", content)

    def test_deploy_script_does_not_mix_terragrunt_all_with_graph(self) -> None:
        content = (ROOT / "scripts/deploy-live.sh").read_text()
        self.assertNotIn("run --all --graph", content)
        self.assertIn("./scripts/validate-aws-kms.sh", content)

    def test_unlock_helper_uses_force_unlock_with_explicit_unit(self) -> None:
        content = (ROOT / "scripts/unlock-terragrunt-unit.sh").read_text()
        self.assertIn("usage: $0 <terragrunt-unit-path> <lock-id>", content)
        self.assertIn('TG_TF_PATH="${TG_TF_PATH:-tofu}" terragrunt', content)
        self.assertIn("--working-dir \"$unit_path\" force-unlock -force \"$lock_id\"", content)
