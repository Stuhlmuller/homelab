locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = []
  spec = {
    destination = {
      namespace = "kube-system"
    }
    sources = [
      {
        repoURL        = local.shared.repo_url
        path           = "clusters/homelab/platform/dns"
        targetRevision = local.shared.target_revision
      }
    ]
    syncPolicy = {
      automated = {
        prune = false
      }
      syncOptions = ["CreateNamespace=false"]
    }
    info = [
      {
        name  = "dns"
        value = "clusters/homelab/platform/dns/README.md"
      },
      {
        name  = "prune"
        value = "disabled because this app adopts all six bootstrap CoreDNS resources"
      }
    ]
  }
}
