include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/argocd-application-kubernetes"
}

dependencies {
  paths = ["../cert-manager"]
}

locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
}

inputs = {
  metadata = {
    name      = "istio"
    namespace = "argocd"
    labels = {
      "app.kubernetes.io/managed-by" = "terragrunt"
      "app.kubernetes.io/part-of"    = "homelab"
    }
  }

  project = "homelab"

  destination = {
    server    = "https://kubernetes.default.svc"
    namespace = "istio-system"
  }

  sources = [
    {
      repo_url        = "https://istio-release.storage.googleapis.com/charts"
      chart           = "base"
      target_revision = "1.27.3"
      helm = {
        release_name           = "istio-base"
        skip_schema_validation = true
        value_files            = ["$values/clusters/homelab/apps/istio/values.yaml"]
      }
    },
    {
      repo_url        = "https://istio-release.storage.googleapis.com/charts"
      chart           = "istiod"
      target_revision = "1.27.3"
      helm = {
        release_name           = "istiod"
        skip_schema_validation = true
        value_files            = ["$values/clusters/homelab/apps/istio/values.yaml"]
      }
    },
    {
      repo_url        = "https://istio-release.storage.googleapis.com/charts"
      chart           = "cni"
      target_revision = "1.27.3"
      helm = {
        release_name           = "istio-cni"
        skip_schema_validation = true
        value_files            = ["$values/clusters/homelab/apps/istio/values.yaml"]
      }
    },
    {
      repo_url        = "https://istio-release.storage.googleapis.com/charts"
      chart           = "ztunnel"
      target_revision = "1.27.3"
      helm = {
        release_name           = "ztunnel"
        skip_schema_validation = true
        value_files            = ["$values/clusters/homelab/apps/istio/values.yaml"]
      }
    },
    {
      repo_url        = "https://istio-release.storage.googleapis.com/charts"
      chart           = "gateway"
      target_revision = "1.27.3"
      helm = {
        release_name           = "istio-ingressgateway"
        skip_schema_validation = true
        value_files            = ["$values/clusters/homelab/apps/istio/values.yaml"]
      }
    },
    {
      repo_url        = local.repo_url
      target_revision = local.target_revision
      ref             = "values"
      directory = {
        include = ".argocd-values-ref-placeholder.yaml"
      }
    },
    {
      repo_url        = local.repo_url
      target_revision = local.target_revision
      path            = "clusters/homelab/apps/istio"
      kustomize       = {}
    }
  ]

  sync_policy = {
    automated = {
      prune     = true
      self_heal = true
    }
    sync_options = [
      "CreateNamespace=true",
      "ServerSideApply=true"
    ]
    retry = {
      limit = "5"
      backoff = {
        duration     = "30s"
        factor       = "2"
        max_duration = "2m"
      }
    }
  }

  ignore_differences = [
    {
      group = "admissionregistration.k8s.io"
      kind  = "ValidatingWebhookConfiguration"
      jq_path_expressions = [
        ".webhooks[]?.clientConfig.caBundle",
        ".webhooks[]?.failurePolicy"
      ]
    },
    {
      group     = "apps"
      kind      = "DaemonSet"
      name      = "ztunnel"
      namespace = "istio-system"
      json_pointers = [
        "/metadata/annotations/deprecated.daemonset.template.generation",
      ]
    }
  ]

  info = [
    {
      name  = "ingress"
      value = "docs/networking-tailnet-ingress.md"
    }
  ]
}
