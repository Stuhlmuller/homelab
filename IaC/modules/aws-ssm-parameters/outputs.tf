output "parameter_names" {
  description = "SSM Parameter Store names managed by this module."
  value       = keys(aws_ssm_parameter.this)
}

output "kms_key_id" {
  description = "KMS key ID used for SSM SecureString parameters."
  value       = var.create_kms_key ? aws_kms_key.this[0].key_id : var.kms_key_id
}
