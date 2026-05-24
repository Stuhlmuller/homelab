include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  self_management_application_manifest = "${get_terragrunt_dir()}/../../../clusters/homelab/argocd/self-management/application.yaml"
  saml_sso_secret_name                 = "argocd-saml-sso"
  saml_sso_store_name                  = "argocd-ssm"
  saml_sso_parameter_prefix            = "/homelab/argocd/saml"
  saml_sso_admin_group                 = "argocd-admins"
}

terraform {
  source = "git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/helm-release?ref=0.3.0"

  after_hook "apply_self_management_application" {
    commands = ["apply"]
    execute = [
      "sh",
      "-c",
      "kubectl wait --for=condition=Established crd/applications.argoproj.io --timeout=180s && kubectl apply -f '${local.self_management_application_manifest}'",
    ]
  }
}

inputs = {
  name             = "argocd"
  namespace        = "argocd"
  create_namespace = true
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  chart_version    = "9.5.15"

  values = [
    yamlencode({
      configs = {
        cm = {
          url          = format("$%s:url", local.saml_sso_secret_name)
          "dex.config" = <<-EOT
            connectors:
              - type: saml
                id: saml
                name: SAML
                config:
                  ssoURL: ${format("$%s:ssoURL", local.saml_sso_secret_name)}
                  caData: ${format("$%s:caData", local.saml_sso_secret_name)}
                  redirectURI: ${format("$%s:callback", local.saml_sso_secret_name)}
                  usernameAttr: email
                  emailAttr: email
                  groupsAttr: groups
                  entityIssuer: ${format("$%s:clientID", local.saml_sso_secret_name)}
          EOT
        }

        params = {
          "server.insecure" = "true"
        }

        rbac = {
          "policy.default" = "role:readonly"
          "policy.csv"     = "g, ${local.saml_sso_admin_group}, role:admin\n"
          scopes           = "[groups, email]"
        }
      }

      dex = {
        enabled = true
      }

      server = {
        service = {
          type = "ClusterIP"
        }
      }

      extraObjects = [
        {
          apiVersion = "external-secrets.io/v1beta1"
          kind       = "SecretStore"
          metadata = {
            name      = local.saml_sso_store_name
            namespace = "argocd"
            labels = {
              "app.kubernetes.io/name"       = local.saml_sso_store_name
              "app.kubernetes.io/part-of"    = "argocd"
              "app.kubernetes.io/managed-by" = "terragrunt"
            }
          }
          spec = {
            provider = {
              aws = {
                service = "ParameterStore"
                region  = "us-east-1"
              }
            }
          }
        },
        {
          apiVersion = "external-secrets.io/v1beta1"
          kind       = "ExternalSecret"
          metadata = {
            name      = local.saml_sso_secret_name
            namespace = "argocd"
            labels = {
              "app.kubernetes.io/name"       = local.saml_sso_secret_name
              "app.kubernetes.io/part-of"    = "argocd"
              "app.kubernetes.io/managed-by" = "terragrunt"
            }
          }
          spec = {
            refreshInterval = "1h"
            secretStoreRef = {
              kind = "SecretStore"
              name = local.saml_sso_store_name
            }
            target = {
              name           = local.saml_sso_secret_name
              creationPolicy = "Owner"
              template = {
                type = "Opaque"
                metadata = {
                  labels = {
                    "app.kubernetes.io/name"       = local.saml_sso_secret_name
                    "app.kubernetes.io/part-of"    = "argocd"
                    "app.kubernetes.io/managed-by" = "external-secrets"
                  }
                }
              }
            }
            data = [
              {
                secretKey = "url"
                remoteRef = {
                  key = "${local.saml_sso_parameter_prefix}/url"
                }
              },
              {
                secretKey = "ssoURL"
                remoteRef = {
                  key = "${local.saml_sso_parameter_prefix}/sso-url"
                }
              },
              {
                secretKey = "caData"
                remoteRef = {
                  key = "${local.saml_sso_parameter_prefix}/ca-data"
                }
              },
              {
                secretKey = "callback"
                remoteRef = {
                  key = "${local.saml_sso_parameter_prefix}/callback-url"
                }
              },
              {
                secretKey = "clientID"
                remoteRef = {
                  key = "${local.saml_sso_parameter_prefix}/client-id"
                }
              },
              {
                secretKey = "clientSecret"
                remoteRef = {
                  key = "${local.saml_sso_parameter_prefix}/client-secret"
                }
              },
            ]
          }
        },
      ]
    })
  ]

  wait          = true
  wait_for_jobs = true
  timeout       = 600
}
