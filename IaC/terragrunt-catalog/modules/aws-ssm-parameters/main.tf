data "aws_caller_identity" "current" {}

data "aws_kms_key" "existing" {
  key_id = var.kms_key_id
}

locals {
  parameter_reader_names = setunion(toset([
    for name, parameter in var.parameters : name
    if parameter.reader_access
  ]), var.additional_parameter_reader_names)
  parameter_reader_policy_chunks = length(var.parameter_reader_iam_user_names) > 0 ? {
    for index, names in chunklist(sort(tolist(local.parameter_reader_names)), 25) :
    format("%02d", index) => names
  } : {}
  external_parameters = {
    for name, parameter in var.parameters :
    name => parameter
    if try(parameter.generated, null) == null
  }
  generated_parameters = {
    for name, parameter in var.parameters :
    name => parameter
    if try(parameter.generated, null) != null
  }
  random_generated_parameters = {
    for name, parameter in local.generated_parameters :
    name => parameter
    if try(parameter.generated.source_parameter, null) == null && try(parameter.generated.kind, "password") == "password"
  }
  hex_generated_parameters = {
    for name, parameter in local.generated_parameters :
    name => parameter
    if try(parameter.generated.source_parameter, null) == null && try(parameter.generated.kind, "password") == "hex"
  }
  private_key_generated_parameters = {
    for name, parameter in local.generated_parameters :
    name => parameter
    if try(parameter.generated.source_parameter, null) == null && contains(["ecdsa_private_key", "rsa_private_key"], try(parameter.generated.kind, "password"))
  }
  sourced_generated_parameters = {
    for name, parameter in local.generated_parameters :
    name => parameter
    if try(parameter.generated.source_parameter, null) != null
  }
  random_generated_values = {
    for name, parameter in local.random_generated_parameters :
    name => "${try(parameter.generated.prefix, "")}${random_password.generated[name].result}"
  }
  private_key_generated_values = {
    for name, parameter in local.private_key_generated_parameters :
    name => tls_private_key.generated[name].private_key_pem
  }
  hex_generated_values = {
    for name, parameter in local.hex_generated_parameters :
    name => random_id.generated[name].hex
  }
  direct_generated_values = merge(
    local.random_generated_values,
    local.private_key_generated_values,
    local.hex_generated_values,
  )
  generated_values = merge(
    local.direct_generated_values,
    {
      for name, parameter in local.sourced_generated_parameters :
      name => local.direct_generated_values[parameter.generated.source_parameter]
    }
  )
}

resource "random_password" "generated" {
  for_each = local.random_generated_parameters

  length           = each.value.generated.length
  lower            = each.value.generated.lower
  override_special = each.value.generated.override_special
  special          = each.value.generated.special
  upper            = each.value.generated.upper
}

resource "random_id" "generated" {
  for_each = local.hex_generated_parameters

  byte_length = each.value.generated.length
}

resource "tls_private_key" "generated" {
  for_each = local.private_key_generated_parameters

  algorithm   = each.value.generated.kind == "rsa_private_key" ? "RSA" : "ECDSA"
  ecdsa_curve = each.value.generated.kind == "rsa_private_key" ? null : "P256"
  rsa_bits    = each.value.generated.kind == "rsa_private_key" ? 2048 : null
}

resource "aws_ssm_parameter" "this" {
  for_each   = local.external_parameters
  depends_on = [aws_iam_group_policy.parameter_reader]

  region      = var.aws_region
  name        = each.key
  description = each.value.description
  type        = "SecureString"
  value       = sensitive(each.value.initial_value)
  key_id      = var.kms_key_id
  tier        = each.value.tier
  tags        = var.tags

  lifecycle {
    create_before_destroy = true

    ignore_changes = [
      value,
    ]
  }
}

resource "aws_ssm_parameter" "generated" {
  for_each   = local.generated_parameters
  depends_on = [aws_iam_group_policy.parameter_reader]

  region      = var.aws_region
  name        = each.key
  description = each.value.description
  type        = "SecureString"
  value       = sensitive(local.generated_values[each.key])
  key_id      = var.kms_key_id
  tier        = each.value.tier
  tags        = var.tags

  lifecycle {
    create_before_destroy = true
  }
}
