variable "aws_region" {
  description = "AWS region inherited from root Terragrunt inputs."
  type        = string
}

variable "kms_key_id" {
  description = "AWS KMS key ID for OpenTofu state encryption."
  type        = string
}

variable "kms_region" {
  description = "AWS region for the KMS key used by OpenTofu state encryption."
  type        = string
  default     = "us-west-2"
}

variable "kms_key_spec" {
  description = "AWS KMS key spec."
  type        = string
  default     = "AES_256"
}

variable "kubernetes_config_path" {
  description = "Kubernetes config path inherited from root Terragrunt inputs."
  type        = string
}

variable "project_name" {
  description = "Project name inherited from root Terragrunt inputs."
  type        = string
}

variable "tags" {
  description = "Default tags inherited from root Terragrunt inputs."
  type        = map(any)
}
