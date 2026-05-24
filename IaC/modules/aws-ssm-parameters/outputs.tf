output "parameter_names" {
  description = "SSM Parameter Store names managed by this module."
  value       = keys(aws_ssm_parameter.this)
}
