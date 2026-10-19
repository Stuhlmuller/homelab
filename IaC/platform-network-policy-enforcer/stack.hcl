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
        path           = "clusters/homelab/platform/network-policy-enforcer"
        targetRevision = local.shared.target_revision
      }
    ]
    syncPolicy = {
      automated = {
        enabled = false
      }
      syncOptions = ["CreateNamespace=false", "ServerSideApply=true"]
    }
    info = [
      {
        name  = "activation"
        value = "Disabled until a reviewed promotion after Harbor pull, dedicated node and active Talos NRI readback"
      }
    ]
  }
}
