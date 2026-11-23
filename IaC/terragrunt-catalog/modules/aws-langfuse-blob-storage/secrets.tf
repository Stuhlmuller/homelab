resource "aws_ssm_parameter" "access_key_id" {
  region      = var.aws_region
  name        = "/homelab/langfuse/s3-access-key-id"
  description = "Langfuse S3 blob-storage access key ID."
  type        = "SecureString"
  value       = sensitive(aws_iam_access_key.langfuse.id)
  key_id      = var.parameter_kms_key_id
  tags        = var.tags
}

resource "aws_ssm_parameter" "secret_access_key" {
  region      = var.aws_region
  name        = "/homelab/langfuse/s3-secret-access-key"
  description = "Langfuse S3 blob-storage secret access key."
  type        = "SecureString"
  value       = sensitive(aws_iam_access_key.langfuse.secret)
  key_id      = var.parameter_kms_key_id
  tags        = var.tags
}
