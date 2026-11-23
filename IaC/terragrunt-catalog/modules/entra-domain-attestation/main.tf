variable "domain_name" {
  description = "Existing verified and federated Entra custom domain to attest."
  type        = string
}

# The one-shot DNS verification is complete. Forget its state without a Graph write.
removed {
  from = msgraph_resource_action.verify

  lifecycle {
    destroy = false
  }
}

data "msgraph_resource" "domain" {
  url         = "domains/${var.domain_name}"
  api_version = "v1.0"

  response_export_values = {
    authentication_type = "authenticationType"
    is_default          = "isDefault"
    is_initial          = "isInitial"
    verified            = "isVerified"
  }

  lifecycle {
    postcondition {
      condition = (
        self.output.verified == true &&
        self.output.authentication_type == "Federated" &&
        self.output.is_default == false &&
        self.output.is_initial == false
      )
      error_message = "The existing Entra domain must be verified, federated, non-default, and non-initial."
    }
  }
}

output "domain_status" {
  description = "The read-only status of the verified, federated domain."
  value       = data.msgraph_resource.domain.output
}
