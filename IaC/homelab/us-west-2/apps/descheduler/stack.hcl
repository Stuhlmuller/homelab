locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["prometheus"]
  spec = {
    destination = {
      namespace = "kube-system"
    }
    sources = [
      {
        repoURL        = "https://kubernetes-sigs.github.io/descheduler"
        chart          = "descheduler"
        path           = "."
        targetRevision = "0.33.0"
        helm = {
          releaseName = "descheduler"
          valueFiles  = ["$values/clusters/homelab/apps/descheduler/values.yaml"]
          parameters = [
            {
              name  = "kind"
              value = "CronJob"
            },
            {
              name  = "suspend"
              value = "true"
            }
          ]
        }
      },
      {
        repoURL = local.shared.repo_url
        path    = "."
        # Stage 1 retains the verified inert profile until the suspended
        # CronJob revision has merged and zero live Pods are observed.
        targetRevision = "934770124f6e3b3c1b0857ce8e510e0ea7a1e894"
        ref            = "values"
        directory = {
          include = ".argocd-values-ref-placeholder.yaml"
        }
      }
    ]
    syncPolicy = {
      syncOptions = ["ServerSideApply=true"]
    }
  }
}
