resource "aws_ssm_parameter" "this" {
  for_each = var.parameters

  name        = each.key
  description = each.value.description
  type        = "SecureString"
  value       = each.value.initial_value
  key_id      = var.kms_key_id
  tier        = each.value.tier
  tags        = var.tags

  lifecycle {
    ignore_changes = [
      value,
    ]
  }
}
