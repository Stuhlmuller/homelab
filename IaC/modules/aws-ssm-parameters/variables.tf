variable "parameters" {
  description = "SSM parameters to create for homelab runtime secret references."
  type = map(object({
    description   = string
    initial_value = optional(string, "REPLACE_ME")
    tier          = optional(string, "Standard")
  }))
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
