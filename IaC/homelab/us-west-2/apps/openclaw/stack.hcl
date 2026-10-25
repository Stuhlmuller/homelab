locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "cert-manager", "istio", "litellm", "platform-storage"]
  spec = {
    project = "homelab-workloads"
    destination = {
      namespace = "ai"
    }
    sources = [
      {
        repoURL        = "https://bjw-s-labs.github.io/helm-charts"
        chart          = "app-template"
        path           = "."
        targetRevision = "4.4.0"
        helm = {
          releaseName = "openclaw"
          valueFiles  = ["$values/clusters/homelab/apps/openclaw/values.yaml"]
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
        path           = "clusters/homelab/apps/openclaw"
        targetRevision = local.shared.target_revision
      }
    ]
    info = [
      {
        name  = "rollout"
        value = "automated; verify LiteLLM and NFS backup coverage before relying on runtime state"
      }
    ]
  }
}
