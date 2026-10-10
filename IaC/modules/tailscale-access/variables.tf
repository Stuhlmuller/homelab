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
