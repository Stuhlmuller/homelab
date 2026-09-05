terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "key_id" {
  description = "Exact existing key UUID to adopt, then retire."
  type        = string
}

variable "alias_name" {
  description = "Existing alias for the retiring key."
  type        = string
}

variable "account_id" {
  description = "Account that already administers the key."
  type        = string
}

variable "retirement_requested" {
  description = "False only during adoption; true schedules the imported key for deletion."
  type        = bool
  default     = true
}

import {
  for_each = var.retirement_requested ? {} : { existing = var.key_id }
  to       = aws_kms_key.legacy[0]
  id       = each.value
}

import {
  for_each = var.retirement_requested ? {} : { existing = var.alias_name }
  to       = aws_kms_alias.legacy[0]
  id       = each.value
}

resource "aws_kms_key" "legacy" {
  count                   = var.retirement_requested ? 0 : 1
  description             = ""
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy = jsonencode({
    Version = "2012-10-17"
    Id      = "key-consolepolicy-3"
    Statement = [{
      Sid       = "Enable IAM User Permissions"
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::${var.account_id}:root" }
      Action    = "kms:*"
      Resource  = "*"
    }]
  })
}

resource "aws_kms_alias" "legacy" {
  count         = var.retirement_requested ? 0 : 1
  name          = var.alias_name
  target_key_id = aws_kms_key.legacy[0].key_id
}
