variable "kms_key_id" {
  description = "AWS KMS key ID used by OpenTofu state and plan encryption."
  type        = string
}

variable "aws_region" {
  description = "AWS region used by the OpenTofu KMS encryption provider."
  type        = string
  default     = "us-east-1"
}

variable "path" {
  description = "Nomad variable path."
  type        = string
}

variable "namespace" {
  description = "Nomad namespace."
  type        = string
  default     = "default"
}

variable "items" {
  description = "Nomad variable items tracked directly in the repository."
  type        = map(string)
  default     = {}
}

variable "ssm_parameters" {
  description = "Map of Nomad variable item keys to AWS SSM parameter names."
  type        = map(string)
  default     = {}
}

variable "ssm_with_decryption" {
  description = "Whether SSM parameters should be read with SecureString decryption enabled."
  type        = bool
  default     = true
}
