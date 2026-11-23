variable "bucket_name" {
  description = "Existing bucket whose encryption configuration this unit owns."
  type        = string
}

variable "default_kms_key_id" {
  description = "Existing default KMS key ARN; explicit per-object keys remain supported."
  type        = string
}

variable "bucket_key_enabled" {
  description = "Cache S3 bucket keys to reduce KMS requests for new object versions."
  type        = bool
}
