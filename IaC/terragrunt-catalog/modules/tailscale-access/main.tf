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

resource "tailscale_dns_configuration" "homelab" {
  magic_dns          = true
  override_local_dns = false
  search_paths       = []

  nameservers {
    address = "1.1.1.2"
  }
  nameservers {
    address = "1.0.0.2"
  }

  split_dns {
    domain = "stinkyboi.com"
    nameservers {
      address = "100.71.150.27"
    }
  }
}

resource "tailscale_tailnet_settings" "homelab" {
  acls_externally_managed_on                  = false
  devices_approval_on                         = false
  devices_auto_updates_on                     = true
  devices_key_duration_days                   = 180
  https_enabled                               = true
  network_flow_logging_on                     = false
  posture_identity_collection_on              = false
  regional_routing_on                         = false
  users_approval_on                           = true
  users_role_allowed_to_join_external_tailnet = "none"
}

resource "tailscale_contacts" "homelab" {
  account {
    email = "rodman@stuhlmuller.net"
  }
  security {
    email = "rodman@stuhlmuller.net"
  }
  support {
    email = "rodman@stuhlmuller.net"
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
