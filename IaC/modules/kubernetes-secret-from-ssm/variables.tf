variable "name" {
  description = "Name of the Kubernetes Secret to create."
  type        = string
}

variable "namespace" {
  description = "Namespace where the Kubernetes Secret should be created."
  type        = string
}

variable "data_ssm_parameter_names" {
  description = "Map of Kubernetes Secret keys to encrypted AWS SSM parameter names."
  type        = map(string)
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
