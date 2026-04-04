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

resource "nomad_csi_volume_registration" "this" {
  volume_id             = var.volume_id
  name                  = var.name
  plugin_id             = var.plugin_id
  external_id           = var.external_id
  namespace             = var.namespace
  context               = var.context
  parameters            = var.parameters
  secrets               = var.secrets
  capacity_min          = var.capacity_min
  capacity_max          = var.capacity_max
  deregister_on_destroy = var.deregister_on_destroy
  dynamic "capability" {
    for_each = var.capabilities
    content {
      access_mode     = capability.value.access_mode
      attachment_mode = capability.value.attachment_mode
    }
  }

  dynamic "mount_options" {
    for_each = var.mount_options == null ? [] : [var.mount_options]
    content {
      fs_type     = try(mount_options.value.fs_type, null)
      mount_flags = try(mount_options.value.mount_flags, null)
    }
  }
}
