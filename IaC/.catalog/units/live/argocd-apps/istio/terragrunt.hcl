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
  paths = ["../cert-manager"]
}

locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
}

inputs = {
  manifest = {
    apiVersion = "argoproj.io/v1alpha1"
    kind       = "Application"

    metadata = {
      name      = "istio"
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
        namespace = "istio-system"
      }

      sources = [
        {
          repoURL        = "https://istio-release.storage.googleapis.com/charts"
          chart          = "base"
          path           = "."
          targetRevision = "1.27.3"
          helm = {
            releaseName          = "istio-base"
            skipSchemaValidation = true
            valueFiles           = ["$values/clusters/homelab/apps/istio/values.yaml"]
          }
        },
        {
          repoURL        = "https://istio-release.storage.googleapis.com/charts"
          chart          = "istiod"
          path           = "."
          targetRevision = "1.27.3"
          helm = {
            releaseName          = "istiod"
            skipSchemaValidation = true
            valueFiles           = ["$values/clusters/homelab/apps/istio/values.yaml"]
          }
        },
        {
          repoURL        = "https://istio-release.storage.googleapis.com/charts"
          chart          = "cni"
          path           = "."
          targetRevision = "1.27.3"
          helm = {
            releaseName          = "istio-cni"
            skipSchemaValidation = true
            valueFiles           = ["$values/clusters/homelab/apps/istio/values.yaml"]
          }
        },
        {
          repoURL        = "https://istio-release.storage.googleapis.com/charts"
          chart          = "ztunnel"
          path           = "."
          targetRevision = "1.27.3"
          helm = {
            releaseName          = "ztunnel"
            skipSchemaValidation = true
            valueFiles           = ["$values/clusters/homelab/apps/istio/values.yaml"]
          }
        },
        {
          repoURL        = "https://istio-release.storage.googleapis.com/charts"
          chart          = "gateway"
          path           = "."
          targetRevision = "1.27.3"
          helm = {
            releaseName          = "istio-ingressgateway"
            skipSchemaValidation = true
            valueFiles           = ["$values/clusters/homelab/apps/istio/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          targetRevision = local.target_revision
          ref            = "values"
          path           = "."
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          targetRevision = local.target_revision
          path           = "clusters/homelab/apps/istio"
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
          group = "admissionregistration.k8s.io"
          kind  = "ValidatingWebhookConfiguration"
          jqPathExpressions = [
            ".webhooks[]?.clientConfig.caBundle",
            ".webhooks[]?.failurePolicy"
          ]
        },
        {
          group     = "apps"
          kind      = "DaemonSet"
          name      = "ztunnel"
          namespace = "istio-system"
          jsonPointers = [
            "/metadata/annotations",
            "/spec/revisionHistoryLimit",
            "/spec/template/metadata/annotations",
            "/spec/template/spec/dnsPolicy",
            "/spec/template/spec/restartPolicy",
            "/spec/template/spec/schedulerName",
            "/spec/template/spec/securityContext",
            "/spec/template/spec/serviceAccount",
          ]
          jqPathExpressions = [
            ".spec.template.spec.containers[]?.env[]?.valueFrom.fieldRef.apiVersion",
            ".spec.template.spec.containers[]?.env[]?.valueFrom.resourceFieldRef.divisor",
            ".spec.template.spec.containers[]?.imagePullPolicy",
            ".spec.template.spec.containers[]?.readinessProbe.failureThreshold",
            ".spec.template.spec.containers[]?.readinessProbe.periodSeconds",
            ".spec.template.spec.containers[]?.readinessProbe.successThreshold",
            ".spec.template.spec.containers[]?.readinessProbe.timeoutSeconds",
            ".spec.template.spec.containers[]?.terminationMessagePath",
            ".spec.template.spec.containers[]?.terminationMessagePolicy",
            ".spec.template.spec.volumes[]?.configMap.defaultMode",
            ".spec.template.spec.volumes[]?.projected.defaultMode",
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
  }
}
