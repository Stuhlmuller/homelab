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
            image = {
              repository = "harbor.stinkyboi.com/mirror/registry.k8s.io/metrics-server/metrics-server"
              tag        = "v0.8.1@sha256:b2d2efaf5ac3b366ed0f839d2412a2c4279d4fc2a2a733f12c52133faed36c41"
            }
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
