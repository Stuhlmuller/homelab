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
        repoURL        = "https://kubernetes-sigs.github.io/metrics-server/"
        chart          = "metrics-server"
        targetRevision = "3.13.1"
        helm = {
          releaseName = "metrics-server"
          valuesObject = {
            args = ["--kubelet-insecure-tls"]
          }
        }
      }
    ]
    syncPolicy = {
      syncOptions = ["CreateNamespace=false", "ServerSideApply=true"]
    }
    info = [
      {
        name  = "purpose"
        value = "provides metrics.k8s.io for HPA and kubectl top"
      }
    ]
  }
}
