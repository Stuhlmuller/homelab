terraform {
  required_version = ">= 1.11.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }

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

data "aws_ssm_parameter" "this" {
  for_each = var.ssm_parameters

  name            = each.value
  with_decryption = var.ssm_with_decryption
}

locals {
  resolved_items = merge(
    var.items,
    {
      for key, parameter in data.aws_ssm_parameter.this :
      key => parameter.value
    },
  )
}

resource "nomad_variable" "this" {
  path      = var.path
  namespace = var.namespace
  items     = local.resolved_items
}
