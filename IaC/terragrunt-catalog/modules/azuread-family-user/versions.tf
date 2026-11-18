terraform {
  required_version = ">= 1.10.0"

  required_providers {
    azuread = {
      source  = "hashicorp/azuread"
      version = "3.9.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.0"
    }
  }

}
