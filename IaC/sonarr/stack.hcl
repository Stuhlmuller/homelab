locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["cert-manager", "istio", "deluge", "media-postgres", "prowlarr", "platform-storage"]
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
          releaseName = "sonarr"
          valueFiles  = ["$values/clusters/homelab/apps/sonarr/values.yaml"]
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
        path           = "clusters/homelab/apps/sonarr"
        targetRevision = local.shared.target_revision
      }
    ]
    info = [
      {
        name  = "rollout"
        value = "automated; verify Deluge, Prowlarr, and NFS backup coverage before relying on media automation"
      }
    ]
  }
}
