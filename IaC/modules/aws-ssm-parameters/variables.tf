variable "parameters" {
  description = "SSM parameters to create for homelab runtime secret references."
  type = map(object({
    description   = string
    initial_value = optional(string, "REPLACE_ME")
    tier          = optional(string, "Standard")
  }))
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
