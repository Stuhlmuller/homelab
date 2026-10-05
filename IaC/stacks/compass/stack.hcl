locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["cert-manager", "istio", "prometheus"]
  spec = {
    destination = {
      namespace = "monitoring"
    }
    sources = [
      {
        repoURL        = "ghcr.io/adinhodovic/charts"
        chart          = "compass"
        path           = "."
        targetRevision = "0.6.0"
        helm = {
          releaseName = "compass"
          valueFiles  = ["$values/clusters/homelab/apps/compass/values.yaml"]
        }
      },
      {
        repoURL        = local.shared.repo_url
        path           = "."
        targetRevision = local.shared.target_revision
        ref            = "values"
        directory = {
          include = ".argocd-values-ref-placeholder.yaml"
        }
      },
      {
        repoURL        = local.shared.repo_url
        path           = "clusters/homelab/apps/compass"
        targetRevision = local.shared.target_revision
      }
    ]
    info = [
      {
        name  = "ingress"
        value = "Octelium target compass.homelab with private Istio SNI backend routing"
      },
      {
        name  = "state"
        value = "stateless Kubernetes service discovery dashboard"
      }
    ]
  }
}
