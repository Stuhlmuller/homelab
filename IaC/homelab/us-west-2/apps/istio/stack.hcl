locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["cert-manager"]
  spec = {
    destination = {
      namespace = "istio-system"
    }
    sources = [
      {
        repoURL        = "https://blob.istio.io/istio-release/charts"
        chart          = "base"
        path           = "."
        targetRevision = "1.27.3"
        helm = {
          releaseName          = "istio-base"
          valueFiles           = ["$values/clusters/homelab/apps/istio/values.yaml"]
          skipSchemaValidation = true
        }
      },
      {
        repoURL        = "https://blob.istio.io/istio-release/charts"
        chart          = "istiod"
        path           = "."
        targetRevision = "1.27.3"
        helm = {
          releaseName = "istiod"
          valueFiles  = ["$values/clusters/homelab/apps/istio/values.yaml"]
          parameters = [
            {
              name  = "pilot.image"
              value = "harbor.stinkyboi.com/mirror/docker.io/istio/pilot:1.27.3-distroless@sha256:70f4f8ccf75ba51187f0920b3f40a6517ba98c068b1b88399a342cbd5e31b857"
            },
            {
              name  = "global.proxy.image"
              value = "harbor.stinkyboi.com/mirror/docker.io/istio/proxyv2:1.27.3-distroless@sha256:0ff2299890e3e5b9fe0e38391b048c0788900f69af27306a7aef3036a59220e1"
            },
            {
              name  = "global.proxy_init.image"
              value = "harbor.stinkyboi.com/mirror/docker.io/istio/proxyv2:1.27.3-distroless@sha256:0ff2299890e3e5b9fe0e38391b048c0788900f69af27306a7aef3036a59220e1"
            },
            {
              name  = "pilot.resources.requests.memory"
              value = "512Mi"
            }
          ]
          skipSchemaValidation = true
        }
      },
      {
        repoURL        = "https://blob.istio.io/istio-release/charts"
        chart          = "cni"
        path           = "."
        targetRevision = "1.27.3"
        helm = {
          releaseName = "istio-cni"
          valueFiles  = ["$values/clusters/homelab/apps/istio/values.yaml"]
          parameters = [
            {
              name  = "image"
              value = "harbor.stinkyboi.com/mirror/docker.io/istio/install-cni:1.27.3-distroless@sha256:cfe35258547be35aed2f3c94b56949d5460c0dd3810b94a16d3310c7e9337e62"
            }
          ]
          skipSchemaValidation = true
        }
      },
      {
        repoURL        = "https://blob.istio.io/istio-release/charts"
        chart          = "ztunnel"
        path           = "."
        targetRevision = "1.27.3"
        helm = {
          releaseName = "ztunnel"
          valueFiles  = ["$values/clusters/homelab/apps/istio/values.yaml"]
          parameters = [
            {
              name  = "image"
              value = "harbor.stinkyboi.com/mirror/docker.io/istio/ztunnel:1.27.3-distroless@sha256:3837029816e78cb6fc88d928dc5c6c58522ab9346772a1409b7f7da00d9de4ce"
            },
            {
              name  = "resources.requests.memory"
              value = "256Mi"
            },
            {
              name  = "env.IPV6_ENABLED"
              value = "false"
            },
            {
              name  = "podLabels.homelab\\.rst\\.io/service-account-issuer-cutover"
              value = "10-1-0-199-v1"
            },
            {
              name  = "updateStrategy.rollingUpdate.maxSurge"
              value = "0"
            },
            {
              name  = "updateStrategy.rollingUpdate.maxUnavailable"
              value = "1"
            }
          ]
          skipSchemaValidation = true
        }
      },
      {
        repoURL        = "https://blob.istio.io/istio-release/charts"
        chart          = "gateway"
        path           = "."
        targetRevision = "1.27.3"
        helm = {
          releaseName          = "istio-ingressgateway"
          valueFiles           = ["$values/clusters/homelab/apps/istio/values.yaml"]
          skipSchemaValidation = true
        }
      },
      {
        repoURL        = "https://blob.istio.io/istio-release/charts"
        chart          = "gateway"
        path           = "."
        targetRevision = "1.27.3"
        helm = {
          releaseName          = "octelium-api-ingressgateway"
          valueFiles           = ["$values/clusters/homelab/apps/istio/octelium-api-gateway-values.yaml"]
          skipSchemaValidation = true
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
        path           = "clusters/homelab/apps/istio"
        targetRevision = local.shared.target_revision
      }
    ]
    ignoreDifferences = [
      {
        group             = "admissionregistration.k8s.io"
        kind              = "ValidatingWebhookConfiguration"
        jqPathExpressions = [".webhooks[]?.clientConfig.caBundle", ".webhooks[]?.failurePolicy"]
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
          "/spec/template/spec/serviceAccount"
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
          ".spec.template.spec.volumes[]?.projected.defaultMode"
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
