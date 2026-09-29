variable "key_name" {
  type        = string
  description = "OpenRouter key name."
}

variable "parameter_name" {
  type        = string
  description = "SSM SecureString destination for the issued key."
}

variable "kms_key_id" {
  type        = string
  description = "Runtime SSM encryption key alias or ARN."
}

variable "tags" {
  type        = map(string)
  description = "Repository ownership tags."
}
