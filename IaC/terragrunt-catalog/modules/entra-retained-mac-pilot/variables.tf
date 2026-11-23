variable "pilot_object_id" {
  description = "Immutable directory object ID of the existing pilot."
  type        = string
}

variable "user_principal_name" {
  description = "Exact expected UPN of the existing pilot."
  type        = string
}

variable "required_verified_domain" {
  description = "Exact expected Federated UPN domain."
  type        = string
}
