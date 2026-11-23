terraform {
  required_version = ">= 1.10.0"

  required_providers {
    azuread = {
      source  = "hashicorp/azuread"
      version = "3.9.0"
    }
    # Decode the legacy state during the non-destructive handoff.
    random = {
      source  = "hashicorp/random"
      version = "3.9.0"
    }
  }
}
