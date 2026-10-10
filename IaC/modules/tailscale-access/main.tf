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
