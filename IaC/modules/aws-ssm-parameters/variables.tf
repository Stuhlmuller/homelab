variable "parameters" {
  description = "SSM parameters to create for homelab runtime secret references."
  type = map(object({
    description = string
    generated = optional(object({
      kind             = optional(string, "password")
      length           = optional(number, 48)
      override_special = optional(string)
      prefix           = optional(string, "")
      source_parameter = optional(string)
      special          = optional(bool, false)
    }))
    initial_value = optional(string, "REPLACE_ME")
    tier          = optional(string, "Standard")
  }))

  validation {
    condition = alltrue([
      for parameter in values(var.parameters) :
      contains(["password", "ecdsa_private_key"], try(parameter.generated.kind, "password"))
    ])
    error_message = "Generated SSM parameters must use kind password or ecdsa_private_key."
  }

  validation {
    condition = alltrue([
      for parameter in values(var.parameters) :
      try(parameter.generated.source_parameter, null) == null || try(parameter.generated.kind, "password") == "password"
    ])
    error_message = "source_parameter is supported only for generated password values."
  }
}

variable "parameter_reader_iam_user_names" {
  description = "Existing IAM user names that should be allowed to read and decrypt the managed SSM parameters."
  type        = set(string)
  default     = []
}

variable "additional_parameter_reader_names" {
  description = "Additional SSM Parameter Store names that reader IAM users should be allowed to read even when this module does not create them."
  type        = set(string)
  default     = []
}

variable "aws_region" {
  description = "AWS region where SSM parameters and their KMS key are managed."
  type        = string
}

variable "create_kms_key" {
  description = "Whether to create the KMS key used to encrypt SecureString parameters."
  type        = bool
  default     = false
}

variable "kms_key_id" {
  description = "KMS key alias or ARN used to encrypt SecureString parameters."
  type        = string
}

variable "kms_key_description" {
  description = "Description for the managed KMS key when create_kms_key is true."
  type        = string
  default     = "Homelab OpenTofu-managed SSM Parameter Store key."
}

variable "tags" {
  description = "Tags applied to every SSM parameter."
  type        = map(string)
  default     = {}
}
