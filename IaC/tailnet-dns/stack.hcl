locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["tailscale", "traefik"]
  spec = {
    destination = {
      namespace = "tailnet-dns"
    }
    sources = [
      {
        # OCI digest observed for chart 4.0.0: sha256:b02209df03b08706179875b6e1887cb6064a589b591a0ce1e809a354811e37a7
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
