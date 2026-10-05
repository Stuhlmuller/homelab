locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "istio", "octelium", "litellm", "platform-storage"]
  spec = {
    syncPolicy = {
      retry = {
        backoff = {
          maxDuration = "3m"
        }
      }
    }
    info = [
      {
        name  = "url"
        value = "https://nofx.stinkyboi.com"
      },
      {
        name  = "rollout"
        value = "automated after generated SSM secrets, External Secrets, NFS, Istio, and Octelium are healthy"
      },
      {
        name  = "storage"
        value = "docs/storage-nfs.md"
      }
    ]
  }
}
