resource "kubernetes_namespace_v1" "external_secrets" {
  metadata {
    name = "external-secrets"
    labels = {
      "name" = "external-secrets"
    }
  }
}

resource "helm_release" "release" {
  name       = "external-secrets"
  chart      = "external-secrets"
  repository = "https://charts.external-secrets.io"
  version    = "1.3.2"
  timeout    = "1500"
  namespace  = kubernetes_namespace_v1.external_secrets.metadata[0].name
}

resource "kubernetes_secret_v1" "name" {
  metadata {
    name      = "aws-ssm-secret"
    namespace = kubernetes_namespace_v1.external_secrets.metadata[0].name
  }
  type = "generic"
  data = {
    "aws_access_key_id"     = "update_me"
    "aws_secret_access_key" = "update_me"
  }
  lifecycle {
    ignore_changes = [data]
  }
}

resource "kubernetes_manifest" "external_secrets_secret_store" {
  manifest = {
    apiVersion = "external-secrets.io/v1"
    kind       = "ClusterSecretStore"
    metadata = {
      name = "parameterstore"
    }
    spec = {
      provider = {
        aws = {
          service = "ParameterStore"
          region  = "us-west-2"
          auth = {
            secretRef = {
              accessKeyIDSecretRef = {
                name      = "aws-ssm-secret"
                key       = "aws_access_key_id"
                namespace = kubernetes_namespace_v1.external_secrets.metadata[0].name
              }
              secretAccessKeySecretRef = {
                name      = "aws-ssm-secret"
                key       = "aws_secret_access_key"
                namespace = kubernetes_namespace_v1.external_secrets.metadata[0].name
              }
            }
          }
        }
      }
    }
  }
}
