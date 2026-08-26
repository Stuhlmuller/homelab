variable "name" {
  description = "Name of the Kubernetes Secret to create."
  type        = string
}

variable "namespace" {
  description = "Namespace where the Kubernetes Secret should be created."
  type        = string
}

variable "aws_region" {
  description = "AWS region containing the SSM parameters."
  type        = string
}

variable "data_ssm_parameter_names" {
  description = "Map of Kubernetes Secret keys to encrypted AWS SSM parameter names."
  type        = map(string)
}

variable "data_revision" {
  description = "Revision of the write-only Kubernetes Secret data; increment after rotating an SSM value."
  type        = number
  default     = 1

  validation {
    condition     = var.data_revision >= 1 && floor(var.data_revision) == var.data_revision
    error_message = "data_revision must be a positive integer."
  }
}

variable "type" {
  description = "Kubernetes Secret type."
  type        = string
  default     = "Opaque"
}

variable "labels" {
  description = "Labels to apply to the Kubernetes Secret."
  type        = map(string)
  default     = {}
}

variable "annotations" {
  description = "Annotations to apply to the Kubernetes Secret."
  type        = map(string)
  default     = {}
}

variable "placeholder_value" {
  description = "Placeholder value that must be replaced before creating the Kubernetes Secret."
  type        = string
  default     = "REPLACE_ME"
}
