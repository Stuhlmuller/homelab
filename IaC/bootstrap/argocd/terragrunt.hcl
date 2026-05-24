include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  self_management_application_manifest = "${get_terragrunt_dir()}/../../../clusters/homelab/argocd/self-management/application.yaml"
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
        params = {
          "server.insecure" = "true"
        }
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
