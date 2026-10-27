locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["cert-manager", "istio", "tailscale"]
  spec = {
    destination = {
      namespace = "traefik"
    }
    sources = [
      {
        repoURL        = "https://bjw-s-labs.github.io/helm-charts"
        chart          = "app-template"
        path           = "."
        targetRevision = "4.4.0"
        helm = {
          releaseName = "traefik"
          valueFiles  = ["$values/clusters/homelab/apps/traefik/values.yaml"]
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
        path           = "clusters/homelab/apps/traefik"
        targetRevision = local.shared.target_revision
      }
    ]
    info = [
      {
        name  = "rollout"
        value = "Private Tailscale ingress and path-limited public Funnel callbacks; verify routes before DNS cutover"
      }
    ]
  }
}
