locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["platform-storage", "grafana"]
  spec = {
    destination = {
      namespace = "monitoring"
    }
    sources = [
      {
        repoURL        = local.shared.repo_url
        path           = "clusters/homelab/platform/maintenance-probe"
        targetRevision = local.shared.target_revision
      }
    ]
    syncPolicy = {
      automated = {
        enabled = true
        prune   = false
      }
      syncOptions = ["CreateNamespace=false", "ServerSideApply=true"]
    }
    info = [
      {
        name  = "activation"
        value = "T023 DaemonSet declared; live placement and path checks pending"
      }
    ]
  }
}
