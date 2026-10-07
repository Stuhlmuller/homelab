include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  root_config                          = read_terragrunt_config(find_in_parent_folders("root.hcl"))
  kubernetes_config_path               = local.root_config.locals.kubernetes_config_path
  self_management_application_manifest = "${get_terragrunt_dir()}/../../../clusters/homelab/argocd/self-management/application.yaml"
  self_management_project_manifest     = "${get_terragrunt_dir()}/../../../clusters/homelab/argocd/self-management/appproject.yaml"
  workloads_project_manifest           = "${get_terragrunt_dir()}/../../../clusters/homelab/argocd/self-management/workloads-appproject.yaml"
  oidc_sso_secret_name                 = "argocd-oidc-sso"
  oidc_sso_issuer                      = "https://login.microsoftonline.com/2aee152b-5281-40d0-8f4b-60faf40514ab/v2.0"
  oidc_sso_admin_group                 = "argocd-admins"
  # Entra object ID for the existing rodman@stinkyboi.com administrator.
  # Argo CD v3 authorizes this immutable Dex federated user ID, not an email.
  oidc_sso_admin_entra_object_id = "08dfba7f-71ea-4eae-ae56-b3fb6cb2ad45"
  argocd_metrics = {
    enabled = true
  }
}

# Preserve the reviewed provider selection while using the pinned catalog module.
generate "provider_versions" {
  path      = "provider-versions_override.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
terraform {
  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "3.2.0"
    }
  }
}
EOF
}

generate "helm_provider" {
  path      = "helm-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "helm" {
  kubernetes = {
    config_path = pathexpand("${local.kubernetes_config_path}")
  }
}
EOF
}

terraform {
  source = "git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/helm-release?ref=19df2cb291eef0084cafb85bed644dcdb082108c"

  after_hook "apply_self_management_application" {
    commands = ["apply"]
    execute = [
      "sh",
      "-c",
      "kubectl wait --for=condition=Established crd/applications.argoproj.io --timeout=180s && kubectl wait --for=condition=Established crd/appprojects.argoproj.io --timeout=180s && kubectl apply -f '${local.self_management_project_manifest}' && kubectl apply -f '${local.workloads_project_manifest}' && kubectl apply -f '${local.self_management_application_manifest}'",
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
          url          = "https://argocd.stinkyboi.com"
          "dex.config" = <<-EOT
            connectors:
              - type: oidc
                id: oidc
                name: OIDC
                config:
                  issuer: ${local.oidc_sso_issuer}
                  clientID: ${format("$%s:clientID", local.oidc_sso_secret_name)}
                  clientSecret: ${format("$%s:clientSecret", local.oidc_sso_secret_name)}
                  userIDKey: oid
                  scopes:
                    - openid
                    - profile
                    - email
                  insecureSkipEmailVerified: true
                  insecureEnableGroups: true
          EOT
        }

        params = {
          "server.insecure" = "true"
        }

        rbac = {
          "policy.default" = "role:readonly"
          "policy.csv"     = "g, ${local.oidc_sso_admin_group}, role:admin\ng, ${local.oidc_sso_admin_entra_object_id}, role:admin\n"
          scopes           = "[groups]"
        }
      }

      dex = {
        enabled = true
      }

      controller = {
        replicas            = 2
        podManagementPolicy = "Parallel"
        metrics             = local.argocd_metrics
        podAnnotations = {
          "homelab.stuhlmuller.dev/sync-timeout-revision" = "v1"
        }
      }

      repoServer = {
        metrics = local.argocd_metrics
      }

      server = {
        service = {
          type = "ClusterIP"
        }
        metrics = local.argocd_metrics
      }
    })
  ]

  wait          = true
  wait_for_jobs = true
  timeout       = 600
}
