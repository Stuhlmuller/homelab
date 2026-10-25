locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["platform-storage", "radarr", "sonarr"]
  spec = {
    destination = {
      namespace = "media"
    }
    sources = [
      {
        repoURL        = "https://bjw-s-labs.github.io/helm-charts"
        chart          = "app-template"
        path           = "."
        targetRevision = "4.4.0"
        helm = {
          releaseName = "bazarr"
          valueFiles  = ["$values/clusters/homelab/apps/bazarr/values.yaml"]
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
        path           = "clusters/homelab/apps/bazarr"
        targetRevision = local.shared.target_revision
      }
    ]
    info = [
      {
        name  = "rollout"
        value = "automated; verify Sonarr/Radarr sync, English subtitle downloads, and retained NFS backup coverage"
      }
    ]
  }
}
