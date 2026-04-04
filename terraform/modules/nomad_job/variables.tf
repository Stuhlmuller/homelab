variable "kms_key_id" {
  description = "AWS KMS key ID used by OpenTofu state and plan encryption."
  type        = string
}

variable "aws_region" {
  description = "AWS region used by the OpenTofu KMS encryption provider."
  type        = string
  default     = "us-east-1"
}

variable "jobspec_content" {
  description = "Inline jobspec content."
  type        = string
  default     = null
}

variable "jobspec_file" {
  description = "Path to a Nomad jobspec file."
  type        = string
  default     = null
}

variable "json_format" {
  description = "Whether the jobspec is JSON."
  type        = bool
  default     = false
}

variable "deregister_on_destroy" {
  description = "Deregister the job on destroy."
  type        = bool
  default     = true
}

variable "purge_on_destroy" {
  description = "Purge the job on destroy."
  type        = bool
  default     = false
}

variable "deregister_on_id_change" {
  description = "Deregister the job if the ID changes."
  type        = bool
  default     = false
}

variable "rerun_if_dead" {
  description = "Rerun the job if it is dead."
  type        = bool
  default     = false
}

variable "detach" {
  description = "Detach after create or update."
  type        = bool
  default     = false
}

variable "policy_override" {
  description = "Override soft mandatory policies."
  type        = bool
  default     = false
}

variable "hcl2_allow_fs" {
  description = "Allow filesystem functions in HCL2 jobspec parsing."
  type        = bool
  default     = false
}

variable "hcl2_vars" {
  description = "Variables used when templating an HCL2 jobspec."
  type        = map(string)
  default     = null
}

variable "timeouts" {
  description = "Optional create and update timeouts."
  type = object({
    create = optional(string)
    update = optional(string)
  })
  default = null
}
