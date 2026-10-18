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
          valuesObject = {
            image = {
              repository = "harbor.stinkyboi.com/mirror/xpkg.crossplane.io/crossplane/crossplane"
              tag        = "v2.3.3@sha256:f1c88a98f113a5cb78d75c7e94e2a7fefdf86ffb3353c63f01697dc5ad855b19"
            }
          }
          # No packages or compositions installed; retain CRDs/RBAC in standby.
          parameters = [
            { name = "replicas", value = "0" },
            { name = "rbacManager.replicas", value = "0" },
          ]
        }
      }
    ]
    syncPolicy = {
      syncOptions = ["CreateNamespace=true", "ServerSideApply=true", "SkipDryRunOnMissingResource=true"]
    }
    info = [
      {
        name  = "rollout"
        value = "core standby; restore replicas before adding providers or compositions"
      },
      {
        name  = "docs"
        value = "clusters/homelab/platform/crossplane/README.md"
      }
    ]
  }
}
