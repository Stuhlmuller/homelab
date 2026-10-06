variable "parameters" {
  description = "SSM parameters to create for homelab runtime secret references."
  type = map(object({
    description = string
    generated = optional(object({
      kind             = optional(string, "password")
      length           = optional(number, 48)
      lower            = optional(bool, true)
      override_special = optional(string)
      prefix           = optional(string, "")
      source_parameter = optional(string)
      special          = optional(bool, false)
      upper            = optional(bool, true)
    }))
    initial_value = optional(string, "REPLACE_ME")
    reader_access = optional(bool, true)
    tier          = optional(string, "Standard")
  }))

  validation {
    condition = alltrue([
      for parameter in values(var.parameters) :
      contains(["password", "hex", "ecdsa_private_key", "rsa_private_key"], try(parameter.generated.kind, "password"))
    ])
    error_message = "Generated SSM parameters must use kind password, hex, ecdsa_private_key, or rsa_private_key."
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

variable "kms_key_id" {
  description = "KMS key alias or ARN used to encrypt SecureString parameters."
  type        = string
}

variable "tags" {
  description = "Tags applied to every SSM parameter."
  type        = map(string)
  default     = {}
}
