locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["../../external-secrets/argocd", "../../platform-storage/argocd"]
  spec = {
    destination = {
      namespace = "media"
    }
    ignoreDifferences = [
      {
        group        = "apps"
        kind         = "StatefulSet"
        name         = "media-postgres"
        namespace    = "media"
        jsonPointers = ["/metadata/annotations", "/spec/volumeClaimTemplates"]
      }
    ]
    info = [
      {
        name  = "rollout"
        value = "automated; replace the SSM password placeholder and verify PostgreSQL readiness before syncing media apps"
      },
      {
        name  = "storage"
        value = "docs/storage-nfs.md"
      }
    ]
  }
}
