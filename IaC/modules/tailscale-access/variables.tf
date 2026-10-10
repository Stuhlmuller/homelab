variable "policy" {
  description = "Reviewed complete repository-owned tailnet policy; import existing ACL before adoption."
  type        = string
  validation {
    condition     = can(jsondecode(var.policy)) && !can(jsondecode(var.policy)._bootstrap_required)
    error_message = "Read and preserve the existing full tailnet policy in the committed policy file before planning adoption."
  }
}

variable "kms_key_id" {
  type = string
}

variable "kms_region" {
  type = string
}

variable "kms_key_spec" {
  type    = string
  default = "AES_256"
}

variable "ci_key_generation" {
  description = "Committed CI key rotation generation. Increment every 60 days; keys expire after 90 days."
  type        = number
  validation {
    condition     = var.ci_key_generation >= 1 && var.ci_key_generation <= 999999 && floor(var.ci_key_generation) == var.ci_key_generation
    error_message = "CI key generation must be a positive integer no greater than 999999."
  }
}
