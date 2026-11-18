variable "user_principal_name" {
  description = "New internal cloud-only user's UPN in a verified managed tenant domain."
  type        = string

  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+$", var.user_principal_name))
    error_message = "user_principal_name must be an explicit UPN."
  }
}

variable "display_name" {
  description = "Display name for the new unprivileged family device user."
  type        = string
}
