locals {
  identities = {
    plan = {
      subject  = "repo:Stuhlmuller/homelab:environment:homelab-plan"
      tag      = "tag:homelab-ci-plan"
      workflow = "Stuhlmuller/homelab/.github/workflows/terragrunt-plan.yml@*"
    }
    apply = {
      subject  = "repo:Stuhlmuller/homelab:environment:homelab-production"
      tag      = "tag:homelab-ci-apply"
      workflow = "Stuhlmuller/homelab/.github/workflows/*@refs/heads/main"
    }
    cordium = {
      subject  = "repo:Stuhlmuller/homelab:ref:refs/heads/*"
      tag      = "tag:homelab-ci-cordium"
      workflow = "Stuhlmuller/homelab/.github/workflows/cordium-*.yml@refs/heads/*"
    }
  }
}

resource "tailscale_acl" "homelab" {
  acl                        = var.policy
  overwrite_existing_content = false
  reset_acl_on_destroy       = false

  lifecycle {
    prevent_destroy = true
  }
}

# Retained unused during the Tailnet Lock transition. Remove in a separately
# reviewed retirement after signed-key CI acceptance; do not bypass prevent_destroy.
resource "tailscale_federated_identity" "github" {
  for_each = local.identities

  description = "Homelab GitHub ${each.key}"
  issuer      = "https://token.actions.githubusercontent.com"
  subject     = each.value.subject
  scopes      = ["auth_keys"]
  tags        = [each.value.tag]
  audience    = "https://github.com/Stuhlmuller/homelab/tailscale/${each.key}"
  custom_claim_rules = {
    repository   = "Stuhlmuller/homelab"
    workflow_ref = each.value.workflow
  }
  depends_on = [tailscale_acl.homelab]

  lifecycle {
    prevent_destroy = true
  }
}

resource "tailscale_tailnet_key" "github" {
  for_each = local.identities

  description         = "Homelab CI ${each.key} generation ${var.ci_key_generation}"
  reusable            = true
  ephemeral           = true
  preauthorized       = true
  expiry              = 7776000 # 90 days; rotate through reviewed generation changes every 60 days.
  recreate_if_invalid = "never"
  tags                = [each.value.tag]
  depends_on          = [tailscale_acl.homelab]

  lifecycle {
    create_before_destroy = true
  }
}
