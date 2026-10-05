# Shared Application defaults; application-specific inputs live in stacks/<app>/stack.hcl.
locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
  argocd_defaults = {
    repo_url        = local.repo_url
    target_revision = local.target_revision
    source_root     = "clusters/homelab/apps"
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"
      metadata = {
        namespace = "argocd"
        labels = {
          "app.kubernetes.io/managed-by" = "terragrunt"
          "app.kubernetes.io/part-of"    = "homelab"
        }
      }
      spec = {
        project = "homelab"
        destination = {
          name   = ""
          server = "https://kubernetes.default.svc"
        }
        syncPolicy = {
          automated = {
            allowEmpty = false
            enabled    = true
            prune      = true
            selfHeal   = true
          }
          syncOptions = ["CreateNamespace=true", "ServerSideApply=true"]
          retry = {
            limit = "5"
            backoff = {
              duration    = "30s"
              factor      = "2"
              maxDuration = "2m"
            }
          }
        }
      }
    }
  }
}
