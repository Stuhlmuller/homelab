locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "platform-storage"]
  spec = {
    ignoreDifferences = [
      {
        group        = "apps"
        kind         = "StatefulSet"
        name         = "octelium-postgres"
        namespace    = "octelium-storage"
        jsonPointers = ["/metadata/annotations", "/spec/volumeClaimTemplates"]
      },
      {
        group        = "apps"
        kind         = "StatefulSet"
        name         = "octelium-redis"
        namespace    = "octelium-storage"
        jsonPointers = ["/metadata/annotations", "/spec/volumeClaimTemplates"]
      }
    ]
    info = [
      {
        name  = "state"
        value = "PostgreSQL and Redis backing stores for octops init"
      }
    ]
  }
}
