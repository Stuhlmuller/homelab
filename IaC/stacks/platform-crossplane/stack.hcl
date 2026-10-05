locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = []
  spec = {
    destination = {
      namespace = "crossplane-system"
    }
    sources = [
      {
        repoURL        = "https://charts.crossplane.io/stable"
        chart          = "crossplane"
        path           = "."
        targetRevision = "2.3.3"
        helm = {
          releaseName = "crossplane"
        }
      }
    ]
    syncPolicy = {
      syncOptions = ["CreateNamespace=true", "ServerSideApply=true", "SkipDryRunOnMissingResource=true"]
    }
    info = [
      {
        name  = "rollout"
        value = "core only; add providers and credentials in purpose-specific changes"
      },
      {
        name  = "docs"
        value = "clusters/homelab/platform/crossplane/README.md"
      }
    ]
  }
}
