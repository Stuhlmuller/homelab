locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults = local.shared.argocd_defaults
  dependencies = [
    "../aws-ssm-parameters",
    "external-secrets",
    "cert-manager",
    "istio",
    "platform-storage",
    "../langfuse-blob-storage"
  ]
  spec = {
    sources = [
      {
        repoURL        = "ghcr.io/langfuse/langfuse-k8s/charts"
        chart          = "langfuse"
        path           = "."
        targetRevision = "2.1.1"
        helm = {
          releaseName = "langfuse"
          valueFiles  = ["$values/clusters/homelab/apps/langfuse/values.yaml"]
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
        path           = "clusters/homelab/apps/langfuse"
        targetRevision = local.shared.target_revision
      }
    ]
    info = [
      {
        name  = "retention"
        value = "single-replica pilot; raw event bodies expire from S3 after 30 days"
      }
    ]
  }
}
