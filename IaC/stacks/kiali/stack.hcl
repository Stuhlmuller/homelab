locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["istio", "prometheus", "grafana"]
  spec = {
    destination = {
      namespace = "istio-system"
    }
    sources = [
      {
        repoURL        = "https://kiali.org/helm-charts"
        chart          = "kiali-operator"
        path           = "."
        targetRevision = "2.26.0"
        helm = {
          releaseName = "kiali-operator"
          valueFiles  = ["$values/clusters/homelab/apps/kiali/values.yaml"]
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
        path           = "clusters/homelab/apps/kiali"
        targetRevision = local.shared.target_revision
      }
    ]
    info = [
      {
        name  = "ingress"
        value = "private app access is through the Octelium service catalog"
      },
      {
        name  = "auth"
        value = "anonymous read-only; Octelium service-proxy access through Istio is allowlisted"
      }
    ]
  }
}
