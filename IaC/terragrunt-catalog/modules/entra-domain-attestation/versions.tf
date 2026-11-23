terraform {
  required_version = ">= 1.10.0"

  required_providers {
    msgraph = {
      source  = "microsoft/msgraph"
      version = "0.5.0"
    }
  }
}
