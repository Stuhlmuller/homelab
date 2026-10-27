locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["platform-dns"]
  spec = {
    sources = [
      {
        repoURL        = "https://charts.external-secrets.io"
        chart          = "external-secrets"
        path           = "."
        targetRevision = "2.0.1"
        helm = {
          releaseName = "external-secrets"
          valueFiles  = ["$values/clusters/homelab/apps/external-secrets/values.yaml"]
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
        path           = "clusters/homelab/apps/external-secrets"
        targetRevision = local.shared.target_revision
      }
    ]
    info = [
      {
        name  = "secrets"
        value = "docs/secrets-aws-ssm.md"
      }
    ]
  }
}
