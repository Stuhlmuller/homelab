variable "kms_key_id" {
  description = "AWS KMS key ID used by OpenTofu state and plan encryption."
  type        = string
}

variable "aws_region" {
  description = "AWS region used by the OpenTofu KMS encryption provider."
  type        = string
  default     = "us-east-1"
}

variable "volume_id" {
  description = "Nomad CSI volume ID."
  type        = string
}

variable "name" {
  description = "Display name for the volume."
  type        = string
}

variable "plugin_id" {
  description = "CSI plugin ID."
  type        = string
}

variable "external_id" {
  description = "Underlying storage provider volume ID."
  type        = string
}

variable "namespace" {
  description = "Nomad namespace."
  type        = string
  default     = "default"
}

variable "context" {
  description = "CSI validation context."
  type        = map(string)
  default     = {}
}

variable "parameters" {
  description = "CSI volume parameters."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "CSI secret values."
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "capabilities" {
  description = "Capabilities exposed by the volume."
  type = set(object({
    access_mode     = string
    attachment_mode = string
  }))
}

variable "mount_options" {
  description = "Optional mount configuration."
  type = object({
    fs_type     = optional(string)
    mount_flags = optional(list(string))
  })
  default = null
}

variable "capacity_min" {
  description = "Minimum requested capacity."
  type        = string
  default     = null
}

variable "capacity_max" {
  description = "Maximum requested capacity."
  type        = string
  default     = null
}

variable "deregister_on_destroy" {
  description = "Deregister the volume on destroy."
  type        = bool
  default     = false
}
