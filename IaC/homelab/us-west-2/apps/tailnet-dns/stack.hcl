locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["../../harbor/argocd", "../../tailscale/argocd", "../../traefik/argocd"]
  spec = {
    destination = {
      namespace = "tailnet-dns"
    }
    sources = [
      {
        repoURL        = "harbor.stinkyboi.com/mirror/helm"
        chart          = "k8s-gateway"
        path           = "."
        targetRevision = "4.0.0"
        helm = {
          releaseName = "tailnet-dns"
          valueFiles  = ["$values/clusters/homelab/platform/tailnet-dns/values.yaml"]
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
        path           = "clusters/homelab/platform/tailnet-dns"
        targetRevision = local.shared.target_revision
      }
    ]
  }
}
