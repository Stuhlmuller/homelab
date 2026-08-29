variable "apply_role_name" {
  description = "Existing GitHub Actions role that runs trusted homelab Terragrunt plans and applies."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,64}$", var.apply_role_name))
    error_message = "apply_role_name must be a valid IAM role name."
  }
}

variable "aws_region" {
  description = "AWS region containing the homelab SSM parameters and runtime-secret KMS key."
  type        = string
}

variable "external_secrets_boundary_policy_name" {
  description = "Name of the operator-owned permissions boundary for the External Secrets IAM user."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,128}$", var.external_secrets_boundary_policy_name))
    error_message = "external_secrets_boundary_policy_name must be a valid IAM policy name."
  }
}

variable "external_secrets_user_name" {
  description = "Existing IAM user used by External Secrets for SSM reads."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,64}$", var.external_secrets_user_name))
    error_message = "external_secrets_user_name must be a valid IAM user name."
  }
}

variable "kms_key_id" {
  description = "Alias shared by the regional KMS keys used for OpenTofu state and homelab SSM parameters."
  type        = string

  validation {
    condition     = startswith(var.kms_key_id, "alias/")
    error_message = "kms_key_id must be a KMS alias resolved independently in the state and runtime-secret regions."
  }
}

variable "parameter_reader_group_name" {
  description = "Exact IAM group that receives the managed SSM parameter reader policies."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,128}$", var.parameter_reader_group_name))
    error_message = "parameter_reader_group_name must be a valid IAM group name."
  }
}

variable "parameter_reader_policy_name_prefix" {
  description = "Name prefix of the managed SSM parameter reader policy family."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,120}$", var.parameter_reader_policy_name_prefix))
    error_message = "parameter_reader_policy_name_prefix must be a valid IAM policy name prefix."
  }
}

variable "parameter_reader_policy_slot_count" {
  description = "Number of exact two-digit managed-policy slots the apply role may administer."
  type        = number
  default     = 10

  validation {
    condition     = var.parameter_reader_policy_slot_count >= 1 && var.parameter_reader_policy_slot_count <= 10 && floor(var.parameter_reader_policy_slot_count) == var.parameter_reader_policy_slot_count
    error_message = "parameter_reader_policy_slot_count must be an integer from 1 through the IAM group attachment limit of 10."
  }
}

variable "plan_policy_name" {
  description = "Name of the managed policy and permissions boundary for the GitHub Actions plan role."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,128}$", var.plan_policy_name))
    error_message = "plan_policy_name must be a valid IAM policy name."
  }
}

variable "plan_role_name" {
  description = "GitHub Actions role used only by homelab pull-request plans."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,64}$", var.plan_role_name))
    error_message = "plan_role_name must be a valid IAM role name."
  }
}

variable "policy_name" {
  description = "Name of the operator-managed policy attached to the GitHub Actions apply role."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,128}$", var.policy_name))
    error_message = "policy_name must be a valid IAM policy name."
  }
}

variable "state_bucket_name" {
  description = "S3 bucket containing the OpenTofu state readable by the plan role."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "state_bucket_name must be a valid S3 bucket name."
  }
}

variable "state_key_prefix" {
  description = "Exact S3 object prefix containing Argo CD Application OpenTofu state."
  type        = string

  validation {
    condition = (
      length(var.state_key_prefix) > 0 &&
      var.state_key_prefix == trimspace(var.state_key_prefix) &&
      var.state_key_prefix == trim(var.state_key_prefix, "/") &&
      !strcontains(var.state_key_prefix, "*")
    )
    error_message = "state_key_prefix must be a non-empty prefix without surrounding slashes, whitespace, or wildcards."
  }
}

variable "tags" {
  description = "Tags applied to the operator-managed IAM policy."
  type        = map(string)
  default     = {}
}
