output "policy_arn" {
  description = "ARN of the managed policy attached to the GitHub Actions apply role."
  value       = aws_iam_policy.parameter_reader_administration.arn
}

output "external_secrets_boundary_policy_arn" {
  description = "ARN of the permissions boundary that caps the External Secrets IAM user."
  value       = aws_iam_policy.external_secrets_boundary.arn
}

output "langfuse_raw_inventory_role_arn" {
  description = "Dedicated production-only GitHub OIDC role for the Langfuse raw-version inventory."
  value       = aws_iam_role.langfuse_raw_inventory.arn
}

output "langfuse_raw_backup_role_arn" {
  description = "Dedicated production-only GitHub OIDC role for exact raw-version offsite copies."
  value       = aws_iam_role.langfuse_raw_backup.arn
}
