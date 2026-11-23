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

variable "required_verified_domain" {
  description = "Optional exact UPN domain that must already be verified, managed, non-default and non-initial before this user can be created."
  type        = string
  default     = null

  validation {
    condition = (
      var.required_verified_domain == null || (
        can(regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$", var.required_verified_domain)) &&
        var.required_verified_domain == lower(var.required_verified_domain)
      )
    )
    error_message = "required_verified_domain must be null or a lowercase root domain."
  }
}
