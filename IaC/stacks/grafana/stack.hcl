locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  metadata = {
    annotations = {
      "argocd.argoproj.io/refresh" = "hard"
    }
  }
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "cert-manager", "istio", "prometheus", "platform-storage"]
  spec = {
    destination = {
      namespace = "monitoring"
    }
    sources = [
      {
        repoURL        = "https://grafana-community.github.io/helm-charts"
        chart          = "grafana"
        path           = "."
        targetRevision = "12.11.2"
        helm = {
          releaseName = "grafana"
          valueFiles  = ["$values/clusters/homelab/apps/grafana/values.yaml"]
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
        path           = "clusters/homelab/apps/grafana"
        targetRevision = local.shared.target_revision
      }
    ]
    info = [
      {
        name  = "alerting-reconcile"
        value = "2026-05-30: tracking main again and bumped the pod annotation to reload alerting provisioning"
      },
      {
        name  = "rollout"
        value = "automated; verify Prometheus and NFS backup coverage before relying on dashboards"
      },
      {
        name  = "ingress"
        value = "private app access is through the Octelium service catalog with Istio SNI backend routing"
      }
    ]
  }
}
