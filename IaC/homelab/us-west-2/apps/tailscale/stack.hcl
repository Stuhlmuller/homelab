locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets"]
  spec = {
    sources = [
      {
        repoURL        = "https://pkgs.tailscale.com/helmcharts"
        chart          = "tailscale-operator"
        path           = "."
        targetRevision = "1.102.3"
        helm = {
          releaseName = "tailscale-operator"
          valueFiles  = ["$values/clusters/homelab/apps/tailscale/values.yaml"]
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
        path           = "clusters/homelab/apps/tailscale"
        targetRevision = local.shared.target_revision
      }
    ]
  }
}
