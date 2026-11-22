terraform {
  required_version = ">= 1.10.0"

  required_providers {
    azuread = {
      source  = "hashicorp/azuread"
      version = "3.9.0"
    }
    msgraph = {
      source  = "microsoft/msgraph"
      version = "0.5.0"
    }
  }
}
