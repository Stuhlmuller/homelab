locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "platform-storage"]
  spec = {
    destination = {
      namespace = "monitoring"
    }
    sources = [
      {
        repoURL        = "https://prometheus-community.github.io/helm-charts"
        chart          = "kube-prometheus-stack"
        path           = "."
        targetRevision = "85.2.0"
        helm = {
          releaseName = "prometheus"
          valueFiles  = ["$values/clusters/homelab/apps/prometheus/values.yaml"]
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
        path           = "clusters/homelab/apps/prometheus"
        targetRevision = local.shared.target_revision
      }
    ]
    info = [
      {
        name  = "rollout"
        value = "automated; verify NFS backup coverage before relying on retained metrics"
      },
      {
        name  = "storage"
        value = "docs/storage-nfs.md"
      }
    ]
  }
}
