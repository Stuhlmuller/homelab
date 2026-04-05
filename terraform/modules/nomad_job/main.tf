terraform {
  required_version = ">= 1.11.0"

  required_providers {
    nomad = {
      source  = "hashicorp/nomad"
      version = "~> 2.5.2"
    }
  }

  encryption {
    key_provider "aws_kms" "main" {
      kms_key_id = var.kms_key_id
      region     = var.aws_region
      key_spec   = "AES_256"
    }

    method "aes_gcm" "main" {
      keys = key_provider.aws_kms.main
    }

    state {
      method   = method.aes_gcm.main
      enforced = true
    }

    plan {
      method   = method.aes_gcm.main
      enforced = true
    }
  }
}

resource "nomad_job" "this" {
  jobspec                 = var.jobspec_content != null ? var.jobspec_content : file(var.jobspec_file)
  json                    = var.json_format
  deregister_on_destroy   = var.deregister_on_destroy
  purge_on_destroy        = var.purge_on_destroy
  deregister_on_id_change = var.deregister_on_id_change
  rerun_if_dead           = var.rerun_if_dead
  detach                  = var.detach
  policy_override         = var.policy_override

  dynamic "hcl2" {
    for_each = var.hcl2_vars == null && !var.hcl2_allow_fs ? [] : [1]
    content {
      allow_fs = var.hcl2_allow_fs
      vars     = var.hcl2_vars
    }
  }

  dynamic "timeouts" {
    for_each = var.timeouts == null ? [] : [var.timeouts]
    content {
      create = try(timeouts.value.create, null)
      update = try(timeouts.value.update, null)
    }
  }
}
