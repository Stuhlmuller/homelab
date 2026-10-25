# A data source keeps the existing domain read-only. The verification action
# below is the only Graph write and remains disabled until DNS is ready.
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
        self.output.authentication_type == "Managed" &&
        self.output.is_default == false &&
        self.output.is_initial == false
      )
      error_message = "The existing domain must be managed, non-default, and non-initial."
    }
  }
}

data "msgraph_resource" "verification_dns" {
  url         = "domains/${var.domain_name}/verificationDnsRecords"
  api_version = "v1.0"

  response_export_values = {
    txt_records = "value[?recordType == 'Txt'].{name: label, value: text, ttl: ttl}"
  }

  lifecycle {
    postcondition {
      condition     = length(self.output.txt_records) == 1
      error_message = "Entra must return exactly one TXT verification record for the configured domain."
    }
  }
}

# The action is deliberately disabled until the DNS owner has published the
# record and authoritative DNS returns the exact Entra-provided value. Standard
# Graph verification is a bodyless POST: its default does not request a domain
# takeover.
resource "msgraph_resource_action" "verify" {
  count        = var.verify_domain ? 1 : 0
  resource_url = "domains/${var.domain_name}"
  action       = "verify"
  method       = "POST"

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [data.msgraph_resource.verification_dns]
}

data "msgraph_resource" "verified_domain" {
  count       = var.verify_domain ? 1 : 0
  url         = "domains/${var.domain_name}"
  api_version = "v1.0"

  response_export_values = {
    authentication_type = "authenticationType"
    is_default          = "isDefault"
    is_initial          = "isInitial"
    verified            = "isVerified"
  }

  depends_on = [msgraph_resource_action.verify]

  lifecycle {
    postcondition {
      condition = (
        self.output.verified == true &&
        self.output.authentication_type == "Managed" &&
        self.output.is_default == false &&
        self.output.is_initial == false
      )
      error_message = "Entra verification must retain the managed, non-default, non-initial domain boundary."
    }
  }
}
