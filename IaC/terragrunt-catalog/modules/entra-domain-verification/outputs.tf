output "domain_status" {
  description = "Read-only status of the existing Entra domain."
  value = var.verify_domain ? data.msgraph_resource.verified_domain[0].output : {
    authentication_type = data.msgraph_resource.domain.output.authentication_type
    is_default          = data.msgraph_resource.domain.output.is_default
    is_initial          = data.msgraph_resource.domain.output.is_initial
    verified            = data.msgraph_resource.domain.output.verified
  }
}

output "verification_txt_record" {
  description = "The exact TXT record the external DNS owner must publish before verify_domain can be enabled."
  value       = one(data.msgraph_resource.verification_dns.output.txt_records)
}
