include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  self_management_application_manifest = "${get_terragrunt_dir()}/../../../clusters/homelab/argocd/self-management/application.yaml"
  oidc_sso_secret_name                 = "argocd-oidc-sso"
  oidc_sso_admin_group                 = "argocd-admins"
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
          url          = "https://argocd.stinkyboi.com"
          "dex.config" = <<-EOT
            connectors:
              - type: oidc
                id: oidc
                name: OIDC
                config:
                  issuer: ${format("$%s:issuer", local.oidc_sso_secret_name)}
                  clientID: ${format("$%s:clientID", local.oidc_sso_secret_name)}
                  clientSecret: ${format("$%s:clientSecret", local.oidc_sso_secret_name)}
                  scopes:
                    - openid
                    - profile
                    - email
                    - groups
                  insecureEnableGroups: true
          EOT
        }

        params = {
          "server.insecure" = "true"
        }

        rbac = {
          "policy.default" = "role:readonly"
          "policy.csv"     = "g, ${local.oidc_sso_admin_group}, role:admin\n"
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
    })
  ]

  wait          = true
  wait_for_jobs = true
  timeout       = 600
}
