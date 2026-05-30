include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/argocd-application-kubernetes"
}

dependencies {
  paths = [
    "../external-secrets",
    "../platform-storage"
  ]
}

locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
}

inputs = {
  metadata = {
    name      = "n8n-postgres"
    namespace = "argocd"
    labels = {
      "app.kubernetes.io/managed-by" = "terragrunt"
      "app.kubernetes.io/part-of"    = "homelab"
    }
  }

  project = "homelab"

  destination = {
    server    = "https://kubernetes.default.svc"
    namespace = "automation"
  }

  sources = [
    {
      repo_url        = local.repo_url
      target_revision = local.target_revision
      path            = "clusters/homelab/apps/n8n-postgres"
      kustomize       = {}
    }
  ]

  sync_policy = {
    automated = {
      prune     = true
      self_heal = true
    }
    managed_namespace_metadata = {
      annotations = {}
      labels = {
        "app.kubernetes.io/name"                     = "automation"
        "app.kubernetes.io/part-of"                  = "homelab"
        "istio.io/dataplane-mode"                    = "ambient"
        "pod-security.kubernetes.io/enforce"         = "baseline"
        "pod-security.kubernetes.io/enforce-version" = "latest"
        "pod-security.kubernetes.io/audit"           = "restricted"
        "pod-security.kubernetes.io/audit-version"   = "latest"
        "pod-security.kubernetes.io/warn"            = "restricted"
        "pod-security.kubernetes.io/warn-version"    = "latest"
      }
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
      group     = "apps"
      kind      = "StatefulSet"
      name      = "n8n-postgres"
      namespace = "automation"
      json_pointers = [
        "/metadata/annotations",
        "/spec/volumeClaimTemplates"
      ]
    }
  ]

  info = [
    {
      name  = "rollout"
      value = "automated; replace the SSM password placeholders and verify PostgreSQL readiness before treating n8n as migrated"
    },
    {
      name  = "storage"
      value = "docs/storage-nfs.md"
    }
  ]
}
