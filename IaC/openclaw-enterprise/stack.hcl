locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["openclaw-enterprise-foundation", "platform-envoy-gateway"]
  spec = {
    project = "openclaw-enterprise"
    destination = {
      namespace = "openclaw-system"
    }
    sources = [
      {
        repoURL        = "harbor.stinkyboi.com/mirror/helm"
        chart          = "openclaw-enterprise"
        targetRevision = "0.1.0"
        helm = {
          releaseName = "oce"
          valueFiles  = ["$values/clusters/homelab/apps/openclaw-enterprise/values.yaml"]
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
        path           = "clusters/homelab/apps/openclaw-enterprise"
        targetRevision = local.shared.target_revision
      }
    ]
    syncPolicy = {
      automated = {
        enabled  = false
        prune    = false
        selfHeal = false
      }
      syncOptions = ["CreateNamespace=false", "ServerSideApply=true"]
      retry = {
        limit = 0
      }
    }
    info = [
      {
        name  = "release"
        value = "serialized full sync only; failed migration needs review before retry"
      },
      {
        name  = "ownership"
        value = "Enterprise owns tenant workloads; Argo owns controller chart and lifecycle hooks only"
      }
    ]
  }
}
