terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.56.0"
    }
    msgraph = {
      source  = "microsoft/msgraph"
      version = "0.5.0"
    }
  }
}
