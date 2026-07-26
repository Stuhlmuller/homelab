include "root" {
  path = find_in_parent_folders("root.hcl")
}

include "kubernetes_provider" {
  path = find_in_parent_folders("kubernetes-provider.hcl")
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
  app_defaults = read_terragrunt_config(find_in_parent_folders("defaults.hcl")).locals
}

inputs = {
  manifest = {
    apiVersion = "argoproj.io/v1alpha1"
    kind       = "Application"

    metadata = {
      name      = "n8n-postgres"
      namespace = "argocd"
      labels = {
        "app.kubernetes.io/managed-by" = "terragrunt"
        "app.kubernetes.io/part-of"    = "homelab"
      }
    }

    spec = {
      project = "homelab"

      destination = {
        name      = ""
        server    = "https://kubernetes.default.svc"
        namespace = "automation"
      }

      sources = [
        {
          repoURL        = local.app_defaults.repo_url
          targetRevision = local.app_defaults.target_revision
          path           = "clusters/homelab/apps/n8n-postgres"
          kustomize      = {}
        }
      ]

      syncPolicy = {
        automated = {
          allowEmpty = false
          enabled    = true
          prune      = true
          selfHeal   = true
        }
        managedNamespaceMetadata = {
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
        syncOptions = [
          "CreateNamespace=true",
          "ServerSideApply=true"
        ]
        retry = {
          limit = "5"
          backoff = {
            duration    = "30s"
            factor      = "2"
            maxDuration = "2m"
          }
        }
      }

      ignoreDifferences = [
        {
          group     = "apps"
          kind      = "StatefulSet"
          name      = "n8n-postgres"
          namespace = "automation"
          jsonPointers = [
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
  }
}
