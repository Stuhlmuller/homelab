output "policy_arn" {
  description = "ARN of the managed policy attached to the GitHub Actions apply role."
  value       = aws_iam_policy.parameter_reader_administration.arn
}
