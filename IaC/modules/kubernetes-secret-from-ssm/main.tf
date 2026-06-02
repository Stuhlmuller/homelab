data "aws_ssm_parameter" "secret_data" {
  for_each = var.data_ssm_parameter_names

  name            = each.value
  with_decryption = true
}

locals {
  secret_data = {
    for key, parameter in data.aws_ssm_parameter.secret_data :
    key => parameter.value
  }

  invalid_secret_keys = [
    for key, value in local.secret_data :
    key
    if trimspace(nonsensitive(value)) == "" || trimspace(nonsensitive(value)) == var.placeholder_value
  ]
}

resource "kubernetes_secret_v1" "this" {
  metadata {
    name        = var.name
    namespace   = var.namespace
    labels      = var.labels
    annotations = var.annotations
  }

  data = local.secret_data
  type = var.type

  lifecycle {
    precondition {
      condition     = length(local.invalid_secret_keys) == 0
      error_message = "SSM parameters for Kubernetes Secret keys ${join(", ", local.invalid_secret_keys)} are empty or still set to the placeholder value."
    }
  }
}
