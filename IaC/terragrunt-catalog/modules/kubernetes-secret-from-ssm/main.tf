data "aws_caller_identity" "current" {}

ephemeral "aws_ssm_parameter" "secret_data" {
  for_each = var.data_ssm_parameter_names

  arn             = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${trimprefix(each.value, "/")}"
  with_decryption = true

  lifecycle {
    postcondition {
      condition     = trimspace(self.value) != "" && trimspace(self.value) != var.placeholder_value
      error_message = "SSM parameter ${each.value} is empty or still set to the placeholder value."
    }
  }
}

locals {
  secret_data = {
    for key, parameter in ephemeral.aws_ssm_parameter.secret_data :
    key => parameter.value
  }
}

resource "kubernetes_secret_v1" "this" {
  metadata {
    name        = var.name
    namespace   = var.namespace
    labels      = var.labels
    annotations = var.annotations
  }

  data_wo          = local.secret_data
  data_wo_revision = var.data_revision
  type             = var.type
}
