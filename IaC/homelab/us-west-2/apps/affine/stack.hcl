locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "cert-manager", "istio", "octelium", "octelium-public", "platform-storage"]
  spec = {
    syncPolicy = {
      retry = {
        backoff = {
          maxDuration = "3m"
        }
      }
    }
    ignoreDifferences = [
      {
        group        = "apps"
        kind         = "StatefulSet"
        name         = "affine-postgres"
        namespace    = "affine"
        jsonPointers = ["/metadata/annotations", "/spec/volumeClaimTemplates"]
      },
      {
        group        = "apps"
        kind         = "StatefulSet"
        name         = "affine-redis"
        namespace    = "affine"
        jsonPointers = ["/metadata/annotations", "/spec/volumeClaimTemplates"]
      }
    ]
    info = [
      {
        name  = "url"
        value = "https://affine.stinkyboi.com"
      },
      {
        name  = "rollout"
        value = "automated after generated SSM secrets, External Secrets, pgvector PostgreSQL, Redis, NFS, Istio, and Octelium are healthy"
      },
      {
        name  = "storage"
        value = "docs/storage-nfs.md"
      }
    ]
  }
}
