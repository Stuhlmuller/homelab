variable "bucket_name" {
  type        = string
  description = "Dedicated bucket name, including the owner account and region suffix."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "Use a 3-63 character lowercase, hyphenated S3 bucket name."
  }
}

variable "expected_account_id" {
  type        = string
  description = "AWS account authorized to own the bucket."

  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "The expected owner must be a 12-digit AWS account ID."
  }
}

variable "aws_region" {
  type        = string
  description = "Explicit region for both the bucket and its AWS-managed S3 KMS key."
}

variable "tags" {
  type        = map(string)
  description = "Repository ownership and purpose tags."
}

variable "publisher" {
  type = object({
    role_name     = string
    object_prefix = string
    subject       = string
    workflow      = string
    ref           = string
    repository_id = number
  })
  description = "Optional prefix-scoped GitHub OIDC publisher; null creates no identity."
  default     = null

  validation {
    condition = var.publisher == null || (
      can(regex("^[a-z0-9][a-z0-9-]{1,62}$", var.publisher.role_name)) &&
      can(regex("^[a-z0-9-]+(/[a-z0-9-]+)+/$", var.publisher.object_prefix)) &&
      can(regex("^repo:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:environment:[A-Za-z0-9_.-]+$", var.publisher.subject)) &&
      can(regex("^[A-Za-z][A-Za-z0-9 -]+$", var.publisher.workflow)) &&
      var.publisher.ref == "refs/heads/main" &&
      var.publisher.repository_id > 0
    )
    error_message = "A publisher needs a named role, path prefix, exact environment subject, workflow, main ref and repository ID."
  }
}
