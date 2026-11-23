locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["../../istio/argocd"]
  spec = {
    destination = {
      namespace = "monitoring"
    }
    sources = [
      {
        repoURL        = local.shared.repo_url
        path           = "clusters/homelab/apps/homepage"
        targetRevision = local.shared.target_revision
      }
    ]
    syncPolicy = {
      syncOptions = ["CreateNamespace=true", "ServerSideApply=true", "PruneLast=true"]
    }
    info = [
      {
        name  = "ingress"
        value = "Octelium target compass.homelab with private Istio SNI backend routing"
      },
      {
        name  = "state"
        value = "Homepage stateless dashboard with Kubernetes Ingress discovery"
      }
    ]
  }
}
