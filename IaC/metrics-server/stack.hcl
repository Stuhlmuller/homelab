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
        repoURL        = "harbor.stinkyboi.com/mirror/helm"
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
