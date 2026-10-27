locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "platform-storage"]
  spec = {
    destination = {
      namespace = "automation"
    }
    syncPolicy = {
      managedNamespaceMetadata = {
        labels = {
          "app.kubernetes.io/name"                     = "automation"
          "app.kubernetes.io/part-of"                  = "homelab"
          "istio.io/dataplane-mode"                    = "ambient"
          "pod-security.kubernetes.io/audit"           = "restricted"
          "pod-security.kubernetes.io/audit-version"   = "latest"
          "pod-security.kubernetes.io/enforce"         = "baseline"
          "pod-security.kubernetes.io/enforce-version" = "latest"
          "pod-security.kubernetes.io/warn"            = "restricted"
          "pod-security.kubernetes.io/warn-version"    = "latest"
        }
        annotations = {}
      }
    }
    ignoreDifferences = [
      {
        group        = "apps"
        kind         = "StatefulSet"
        name         = "n8n-postgres"
        namespace    = "automation"
        jsonPointers = ["/metadata/annotations", "/spec/volumeClaimTemplates"]
      }
    ]
    info = [
      {
        name  = "rollout"
        value = "automated; verify PostgreSQL readiness before starting n8n"
      },
      {
        name  = "storage"
        value = "docs/storage-nfs.md"
      }
    ]
  }
}
