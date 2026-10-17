locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = []
  spec = {
    sources = [
      {
        repoURL        = "https://argoproj.github.io/argo-helm"
        chart          = "argocd-image-updater"
        path           = "."
        targetRevision = "1.3.1"
        helm = {
          releaseName = "argocd-image-updater"
          valueFiles  = ["$values/clusters/homelab/apps/argocd-image-updater/values.yaml"]
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
        path           = "clusters/homelab/apps/argocd-image-updater"
        targetRevision = local.shared.target_revision
      }
    ]
    destination = {
      namespace = "argocd"
    }
    syncPolicy = {
      automated = {
        allowEmpty = true
      }
    }
    info = [
      {
        name  = "purpose"
        value = "Paused digest updater; GitHub App proposals remain disabled until promotion gates pass"
      }
    ]
  }
}
