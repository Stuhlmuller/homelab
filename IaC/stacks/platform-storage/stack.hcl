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
        path           = "clusters/homelab/platform/storage"
        targetRevision = local.shared.target_revision
      }
    ]
    syncPolicy = {
      syncOptions = ["CreateNamespace=false"]
    }
    info = [
      {
        name  = "rollout"
        value = "automated; verify existing NFS provisioner and backup coverage before relying on PVCs"
      },
      {
        name  = "storage"
        value = "docs/storage-nfs.md"
      }
    ]
  }
}
