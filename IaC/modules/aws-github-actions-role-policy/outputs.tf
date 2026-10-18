output "policy_arn" {
  description = "ARN of the managed policy attached to the GitHub Actions apply role."
  value       = aws_iam_policy.parameter_reader_administration.arn
}

output "external_secrets_boundary_policy_arn" {
  description = "ARN of the permissions boundary that caps the External Secrets IAM user."
  value       = aws_iam_policy.external_secrets_boundary.arn
}

output "renovate_transfer_role_arn" {
  description = "Temporary companion-repository role for transferring the existing Renovate App credentials."
  value       = aws_iam_role.renovate_transfer.arn
}
