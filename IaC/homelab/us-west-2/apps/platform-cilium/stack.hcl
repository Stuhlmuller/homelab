locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["../../platform-dns/argocd"]
  spec = {
    destination = {
      namespace = "kube-system"
    }
    sources = [
      {
        repoURL        = "https://helm.cilium.io"
        chart          = "cilium"
        targetRevision = "1.20.5"
        helm = {
          releaseName = "cilium"
          valueFiles = [
            "$values/clusters/homelab/platform/cilium/values-migration.yaml",
            "$values/clusters/homelab/platform/cilium/values-homelab.yaml",
          ]
        }
      },
      {
        repoURL        = local.shared.repo_url
        targetRevision = local.shared.target_revision
        ref            = "values"
      },
      {
        repoURL        = local.shared.repo_url
        path           = "clusters/homelab/platform/cilium"
        targetRevision = local.shared.target_revision
        directory = {
          include = "node-migration.yaml"
        }
      }
    ]
    syncPolicy = {
      automated = {
        enabled = true
        prune   = false
      }
      syncOptions = ["CreateNamespace=false", "ServerSideApply=true"]
    }
    info = [
      {
        name  = "activation"
        value = "coexistence overlay; node migration is a separate stage"
      }
    ]
  }
}
