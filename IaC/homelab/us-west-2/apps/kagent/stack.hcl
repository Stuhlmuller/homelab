locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["../../external-secrets/argocd", "../../istio/argocd", "../../litellm/argocd"]
  spec = {
    sources = [
      {
        repoURL        = "oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds"
        path           = "."
        targetRevision = "0.10.6"
        helm = {
          releaseName = "kagent-crds"
          valueFiles  = ["$values/clusters/homelab/apps/kagent/crds-values.yaml"]
        }
      },
      {
        repoURL        = "oci://ghcr.io/kagent-dev/kagent/helm/kagent"
        path           = "."
        targetRevision = "0.10.6"
        helm = {
          releaseName = "kagent"
          valueFiles  = ["$values/clusters/homelab/apps/kagent/values.yaml"]
        }
      },
      {
        repoURL        = local.shared.repo_url
        path           = "clusters/homelab/apps/kagent"
        targetRevision = local.shared.target_revision
        ref            = "values"
      }
    ]
  }
}
