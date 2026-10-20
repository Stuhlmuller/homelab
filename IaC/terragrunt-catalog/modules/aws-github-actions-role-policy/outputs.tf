output "policy_arn" {
  description = "ARN of the managed policy attached to the GitHub Actions apply role."
  value       = aws_iam_policy.parameter_reader_administration.arn
}

output "plan_role_arn" {
  description = "ARN of the read-only GitHub Actions role for reviewed pull-request plans."
  value       = aws_iam_role.github_actions_plan.arn
}

output "external_secrets_boundary_policy_arn" {
  description = "ARN of the permissions boundary that caps the External Secrets IAM user."
  value       = aws_iam_policy.external_secrets_boundary.arn
}
