variable "apply_role_name" {
  description = "Existing GitHub Actions role that runs trusted homelab Terragrunt plans and applies."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,64}$", var.apply_role_name))
    error_message = "apply_role_name must be a valid IAM role name."
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

variable "policy_name" {
  description = "Name of the operator-managed policy attached to the GitHub Actions apply role."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,128}$", var.policy_name))
    error_message = "policy_name must be a valid IAM policy name."
  }
}

variable "tags" {
  description = "Tags applied to the operator-managed IAM policy."
  type        = map(string)
  default     = {}
}
