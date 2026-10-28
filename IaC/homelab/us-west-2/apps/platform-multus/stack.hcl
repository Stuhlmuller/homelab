locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = []
  spec = {
    destination = {
      namespace = "kube-system"
    }
    sources = [
      {
        repoURL        = local.shared.repo_url
        path           = "clusters/homelab/platform/multus"
        targetRevision = local.shared.target_revision
      }
    ]
    syncPolicy = {
      syncOptions = ["ServerSideApply=true"]
    }
    info = [
      {
        name  = "platform"
        value = "Talos-compatible Multus thick CNI for Octelium data-plane workloads"
      }
    ]
  }
}
