variable "bucket_name" {
  type        = string
  description = "Dedicated Langfuse raw-event bucket name, including owner account and region suffix."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "Use a 3-63 character lowercase, hyphenated S3 bucket name."
  }
}

variable "expected_account_id" {
  type        = string
  description = "AWS account authorized to own the Langfuse bucket."

  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "The expected owner must be a 12-digit AWS account ID."
  }
}

variable "aws_region" {
  type        = string
  description = "Explicit region for the bucket and its AWS-managed S3 KMS key."
}

variable "parameter_kms_key_id" {
  type        = string
  description = "KMS key alias or ARN encrypting SSM runtime credentials."
}

variable "tags" {
  type        = map(string)
  description = "Repository ownership and purpose tags."
}
