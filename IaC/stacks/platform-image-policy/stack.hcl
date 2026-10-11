locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["harbor"]
  spec = {
    destination = {
      namespace = "kube-system"
    }
    sources = [
      {
        repoURL        = local.shared.repo_url
        path           = "clusters/homelab/platform/image-policy"
        targetRevision = local.shared.target_revision
      }
    ]
    syncPolicy = {
      syncOptions = ["CreateNamespace=false", "ServerSideApply=true"]
    }
  }
}
