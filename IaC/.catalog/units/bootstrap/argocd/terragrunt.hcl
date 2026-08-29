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
  oidc_sso_admin_email                 = "rodman@stuhlmuller.net"
  argocd_metrics = {
    enabled = true
  }
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
      global = {
        image = {
          tag = "v3.4.2@sha256:c612d570cb6d6ff29afb72932c1bfe98a1ecc234df50f8ea4873fb7066e760fc"
        }
      }

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
          "policy.csv"     = "g, ${local.oidc_sso_admin_group}, role:admin\ng, ${local.oidc_sso_admin_email}, role:admin\n"
          scopes           = "[groups, email]"
        }
      }

      dex = {
        enabled = true
        image = {
          tag = "v2.45.1@sha256:8499afd690c437f52301efd2b05b2455da5bd2dfc20332cd697dc9937f808462"
        }
      }

      redis = {
        image = {
          tag = "8.2.3-alpine@sha256:08ad0b1d280850169a790dba1393ff7a90aef951fc19632cf4d3ce4f78e679ba"
        }
      }

      controller = {
        metrics = local.argocd_metrics
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
