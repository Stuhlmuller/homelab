locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "cert-manager", "istio", "platform-storage", "prometheus", "traefik"]
  spec = {
    destination = {
      namespace = "monitoring"
    }
    sources = [
      {
        repoURL        = "https://bjw-s-labs.github.io/helm-charts"
        chart          = "app-template"
        path           = "."
        targetRevision = "4.4.0"
        helm = {
          releaseName = "uptime-kuma"
          valueFiles  = ["$values/clusters/homelab/apps/uptime-kuma/values.yaml"]
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
        path           = "clusters/homelab/apps/uptime-kuma"
        targetRevision = local.shared.target_revision
      }
    ]
    info = [{
      name  = "rollout"
      value = "private uptime monitoring; retained local SQLite and NFS backup; require pinned image publication before registration"
    }]
  }
}
