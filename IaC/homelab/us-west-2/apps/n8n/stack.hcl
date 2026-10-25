locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "cert-manager", "istio", "platform-storage", "n8n-postgres"]
  spec = {
    destination = {
      namespace = "automation"
    }
    sources = [
      {
        repoURL        = "https://bjw-s-labs.github.io/helm-charts"
        chart          = "app-template"
        path           = "."
        targetRevision = "4.4.0"
        helm = {
          releaseName = "n8n"
          valueFiles  = ["$values/clusters/homelab/apps/n8n/values.yaml"]
        }
      },
      {
        repoURL        = local.shared.repo_url
        path           = "."
        targetRevision = local.shared.target_revision
        ref            = "values"
        directory = {
          include = ".argocd-values-ref-placeholder.yaml"
        }
      },
      {
        repoURL        = local.shared.repo_url
        path           = "clusters/homelab/apps/n8n"
        targetRevision = local.shared.target_revision
      }
    ]
    info = [
      {
        name  = "rollout"
        value = "automated; preserve the instance encryption key on the n8n PVC and verify n8n-postgres plus NFS backup coverage before relying on automation history"
      }
    ]
  }
}
