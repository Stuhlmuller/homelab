variable "aws_region" {
  description = "AWS region containing the protected Google Workspace metadata parameter."
  type        = string
}

variable "domain_name" {
  description = "Verified Entra custom domain to federate with Google Workspace."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$", var.domain_name))
    error_message = "domain_name must be a lowercase root domain."
  }
}

variable "metadata_parameter_name" {
  description = "SecureString holding validated Google Workspace SAML metadata extracted by the repository-owned transfer script."
  type        = string

  validation {
    condition     = startswith(var.metadata_parameter_name, "/homelab/")
    error_message = "metadata_parameter_name must use the /homelab/ prefix."
  }
}
