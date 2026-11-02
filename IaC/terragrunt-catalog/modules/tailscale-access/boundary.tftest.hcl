mock_provider "tailscale" {}
mock_provider "tailscale" {
  alias = "codex_bootstrap"
}
mock_provider "aws" {}

variables {
  aws_region        = "us-west-2"
  ci_key_generation = 1
  policy            = "{\"grants\":[]}"
  kms_key_id        = "alias/test-only"
  kms_region        = "us-east-1"
  kms_key_spec      = "AES_256"
}

run "identity_boundaries" {
  command = plan
  assert {
    condition     = !tailscale_acl.homelab.overwrite_existing_content && !tailscale_acl.homelab.reset_acl_on_destroy
    error_message = "Existing policy adoption must require import and must never reset policy on destroy."
  }
  assert {
    condition     = tailscale_federated_identity.github["plan"].subject == "repo:Stuhlmuller/homelab:environment:homelab-plan" && tailscale_federated_identity.github["apply"].subject == "repo:Stuhlmuller/homelab:environment:homelab-production"
    error_message = "Plan and apply identities must remain bound to separate protected environments."
  }
  assert {
    condition     = alltrue([for identity in tailscale_federated_identity.github : identity.scopes == toset(["auth_keys"])])
    error_message = "CI identities may enroll ephemeral nodes but must not administer tailnet policy or identities."
  }
  assert {
    condition     = tailscale_federated_identity.github["apply"].custom_claim_rules.workflow_ref == "Stuhlmuller/homelab/.github/workflows/*@refs/heads/main" && tailscale_federated_identity.github["cordium"].tags == toset(["tag:homelab-ci-cordium"])
    error_message = "Production trust stays on main; Cordium must not receive either Kubernetes CI tag."
  }
}

run "reject_unknown_policy_baseline" {
  command = plan
  variables {
    policy = "{\"_bootstrap_required\":true}"
  }
  expect_failures = [var.policy]
}

run "locked_ci_keys" {
  command = plan
  assert {
    condition = alltrue([for name, key in tailscale_tailnet_key.github :
      key.reusable && key.ephemeral && key.preauthorized && key.expiry == 7776000 &&
      key.recreate_if_invalid == "never" && key.tags == toset(["tag:homelab-ci-${name}"]) &&
      key.description == "Homelab CI ${name} generation 1"
    ]) && length(tailscale_tailnet_key.github) == 3
    error_message = "CI keys must remain separate, tagged, ephemeral, reusable and bounded to 90 days with explicit generation rotation."
  }
}

run "reject_untracked_rotation" {
  command = plan
  variables {
    ci_key_generation = 0
  }
  expect_failures = [var.ci_key_generation]
}

run "codex_signer_boundary" {
  command = plan
  assert {
    condition     = tailscale_webhook.codex_signer.subscriptions == toset(["categoryTailnetManagement"])
    error_message = "Use the pinned provider management category; only signature events are handled."
  }
  assert {
    condition     = tailscale_oauth_client.codex_signer.scopes == toset(["devices:core:read"])
    error_message = "The runtime reader must not write device or tailnet configuration."
  }
  assert {
    condition     = tailscale_tailnet_key.codex_cloud.ephemeral && tailscale_tailnet_key.codex_cloud.reusable && tailscale_tailnet_key.codex_cloud.tags == toset(["tag:codex-cloud"])
    error_message = "Cloud enrollment must use only the dedicated ephemeral Codex tag."
  }
  assert {
    condition     = !tailscale_tailnet_key.codex_signer.ephemeral && !tailscale_tailnet_key.codex_signer.reusable && tailscale_tailnet_key.codex_signer.tags == toset(["tag:codex-cloud-signer"])
    error_message = "Signer enrollment must be single-use and persistent."
  }
  assert {
    condition     = alltrue([for parameter in aws_ssm_parameter.codex_signer : parameter.type == "SecureString" && parameter.key_id == "alias/aws/ssm"])
    error_message = "Enrollment and webhook credentials belong in encrypted SSM parameters."
  }
}
