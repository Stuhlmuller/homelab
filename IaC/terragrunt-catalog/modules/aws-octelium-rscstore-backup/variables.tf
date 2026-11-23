variable "bucket_name" {
  type        = string
  description = "The existing versioned application backup bucket name."
}

variable "expected_account_id" {
  type        = string
  description = "AWS account that owns the backup bucket and GitHub OIDC provider."
}

variable "aws_region" {
  type        = string
  description = "Region of the backup bucket and its S3 KMS key."
}

variable "tags" {
  type        = map(string)
  description = "Repository ownership and purpose tags."
}
