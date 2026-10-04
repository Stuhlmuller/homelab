# Application entries below contain only deviations from these shared defaults.
# The unit template generates the raw CRD; live paths remain stable state keys.
locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
  argocd_defaults = {
    repo_url        = local.repo_url
    target_revision = local.target_revision
    source_root     = "clusters/homelab/apps"
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"
      metadata = {
        namespace = "argocd"
        labels = {
          "app.kubernetes.io/managed-by" = "terragrunt"
          "app.kubernetes.io/part-of"    = "homelab"
        }
      }
      spec = {
        project = "homelab"
        destination = {
          name   = ""
          server = "https://kubernetes.default.svc"
        }
        syncPolicy = {
          automated = {
            allowEmpty = false
            enabled    = true
            prune      = true
            selfHeal   = true
          }
          syncOptions = ["CreateNamespace=true", "ServerSideApply=true"]
          retry = {
            limit = "5"
            backoff = {
              duration    = "30s"
              factor      = "2"
              maxDuration = "2m"
            }
          }
        }
      }
    }
  }
}
unit "bootstrap_argocd" {
  source                  = "./.catalog/units/bootstrap/argocd"
  path                    = "bootstrap/argocd"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_affine" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/affine"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "cert-manager", "istio", "octelium", "octelium-public", "platform-storage"]
    spec = {
      syncPolicy = {
        retry = {
          backoff = {
            maxDuration = "3m"
          }
        }
      }
      ignoreDifferences = [
        {
          group        = "apps"
          kind         = "StatefulSet"
          name         = "affine-postgres"
          namespace    = "affine"
          jsonPointers = ["/metadata/annotations", "/spec/volumeClaimTemplates"]
        },
        {
          group        = "apps"
          kind         = "StatefulSet"
          name         = "affine-redis"
          namespace    = "affine"
          jsonPointers = ["/metadata/annotations", "/spec/volumeClaimTemplates"]
        }
      ]
      info = [
        {
          name  = "url"
          value = "https://affine.stinkyboi.com"
        },
        {
          name  = "rollout"
          value = "automated after generated SSM secrets, External Secrets, pgvector PostgreSQL, Redis, NFS, Istio, and Octelium are healthy"
        },
        {
          name  = "storage"
          value = "docs/storage-nfs.md"
        }
      ]
    }
  }
}

unit "argocd_apps_argocd_image_updater" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/argocd-image-updater"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = []
    spec = {
      destination = {
        namespace = "argocd"
      }
      syncPolicy = {
        automated = {
          allowEmpty = true
        }
      }
      info = [
        {
          name  = "purpose"
          value = "retirement tombstone; Renovate owns repository image updates"
        }
      ]
    }
  }
}

unit "argocd_apps_cert_manager" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/cert-manager"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets"]
    spec = {
      sources = [
        {
          repoURL        = "https://charts.jetstack.io"
          chart          = "cert-manager"
          path           = "."
          targetRevision = "v1.20.3"
          helm = {
            releaseName = "cert-manager"
            valueFiles  = ["$values/clusters/homelab/apps/cert-manager/values-v1.20.3.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/cert-manager"
          targetRevision = local.target_revision
        }
      ]
    }
  }
}

unit "argocd_apps_compass" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/compass"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["cert-manager", "istio", "prometheus"]
    spec = {
      destination = {
        namespace = "monitoring"
      }
      sources = [
        {
          repoURL        = "ghcr.io/adinhodovic/charts"
          chart          = "compass"
          path           = "."
          targetRevision = "0.6.0"
          helm = {
            releaseName = "compass"
            valueFiles  = ["$values/clusters/homelab/apps/compass/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/compass"
          targetRevision = local.target_revision
        }
      ]
      info = [
        {
          name  = "ingress"
          value = "Octelium target compass.homelab with private Istio SNI backend routing"
        },
        {
          name  = "state"
          value = "stateless Kubernetes service discovery dashboard"
        }
      ]
    }
  }
}

unit "argocd_apps_cordium" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/cordium"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "octelium-cluster", "octelium-enterprise", "platform-storage"]
    spec = {
      destination = {
        namespace = "octelium"
      }
      syncPolicy = {
        syncOptions = ["CreateNamespace=false", "ServerSideApply=true"]
      }
      info = [
        {
          name  = "bootstrap"
          value = "Runs cordium-genesis 0.12.7 against the self-hosted Octelium Cluster"
        },
        {
          name  = "access"
          value = "Human browser access and agent API access are separate Octelium identities and Services"
        },
        {
          name  = "state"
          value = "Cordium runtime resources are generated by upstream genesis and Octelium controllers"
        }
      ]
    }
  }
}

unit "argocd_apps_deluge" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/deluge"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "cert-manager", "istio", "platform-storage"]
    spec = {
      destination = {
        namespace = "media"
      }
      sources = [
        {
          repoURL        = "https://bjw-s-labs.github.io/helm-charts"
          chart          = "app-template"
          path           = "."
          targetRevision = "4.4.0"
          helm = {
            releaseName = "deluge"
            valueFiles  = ["$values/clusters/homelab/apps/deluge/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/deluge"
          targetRevision = local.target_revision
        }
      ]
      info = [
        {
          name  = "rollout"
          value = "automated; verify NFS backup coverage before relying on downloads"
        }
      ]
    }
  }
}

unit "argocd_apps_descheduler" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/descheduler"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
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
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
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
}

unit "argocd_apps_dispatcharr" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/dispatcharr"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "cert-manager", "istio", "platform-storage"]
    spec = {
      project = "homelab-workloads"
      destination = {
        namespace = "media"
      }
      sources = [
        {
          repoURL        = "https://bjw-s-labs.github.io/helm-charts"
          chart          = "app-template"
          path           = "."
          targetRevision = "4.4.0"
          helm = {
            releaseName = "dispatcharr"
            valueFiles  = ["$values/clusters/homelab/apps/dispatcharr/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/dispatcharr"
          targetRevision = local.target_revision
        }
      ]
      info = [
        {
          name  = "rollout"
          value = "automated; uses dedicated PostgreSQL plus in-pod Redis; complete first-run IPTV source and admin setup through the Octelium-protected UI"
        }
      ]
    }
  }
}

unit "argocd_apps_external_secrets" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/external-secrets"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["platform-dns"]
    spec = {
      sources = [
        {
          repoURL        = "https://charts.external-secrets.io"
          chart          = "external-secrets"
          path           = "."
          targetRevision = "2.0.1"
          helm = {
            releaseName = "external-secrets"
            valueFiles  = ["$values/clusters/homelab/apps/external-secrets/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/external-secrets"
          targetRevision = local.target_revision
        }
      ]
      info = [
        {
          name  = "secrets"
          value = "docs/secrets-aws-ssm.md"
        }
      ]
    }
  }
}

unit "argocd_apps_fleet" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/fleet"
  no_dot_terragrunt_stack = true

  values = {
    defaults = local.argocd_defaults
    dependencies = [
      "../aws-ssm-parameters",
      "external-secrets",
      "cert-manager",
      "istio",
      "octelium",
      "octelium-public",
      "platform-storage"
    ]
    spec = {
      syncPolicy = {
        retry = {
          backoff = {
            maxDuration = "3m"
          }
        }
      }
      info = [
        {
          name  = "url"
          value = "https://fleet.stinkyboi.com"
        },
        {
          name  = "rollout"
          value = "generated SSM secrets, External Secrets, MySQL, Redis, NFS, Istio, and public device ingress must be healthy before enrollment"
        },
        {
          name  = "storage"
          value = "clusters/homelab/apps/fleet/README.md"
        }
      ]
    }
  }
}

unit "argocd_apps_github_actions_runner" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/github-actions-runner"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = []
    spec = {
      syncPolicy = {
        automated = {
          allowEmpty = true
        }
        syncOptions = ["ServerSideApply=true"]
      }
    }
  }
}

unit "argocd_apps_grafana" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/grafana"
  no_dot_terragrunt_stack = true

  values = {
    metadata = {
      annotations = {
        "argocd.argoproj.io/refresh" = "hard"
      }
    }
    defaults     = local.argocd_defaults
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
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/grafana"
          targetRevision = local.target_revision
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
}

unit "argocd_apps_grafana_alert_cleanup" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/grafana-alert-cleanup"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "istio"]
    spec = {
      destination = {
        namespace = "monitoring"
      }
      syncPolicy = {
        automated = {
          allowEmpty = true
        }
        syncOptions = ["ServerSideApply=true"]
      }
      info = [
        {
          name  = "purpose"
          value = "retirement tombstone that prunes the completed Grafana alert cleanup resources"
        }
      ]
    }
  }
}

unit "argocd_apps_istio" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/istio"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["cert-manager"]
    spec = {
      destination = {
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
            valueFiles           = ["$values/clusters/homelab/apps/istio/values.yaml"]
            skipSchemaValidation = true
          }
        },
        {
          repoURL        = "https://istio-release.storage.googleapis.com/charts"
          chart          = "istiod"
          path           = "."
          targetRevision = "1.27.3"
          helm = {
            releaseName = "istiod"
            valueFiles  = ["$values/clusters/homelab/apps/istio/values.yaml"]
            parameters = [
              {
                name  = "pilot.resources.requests.memory"
                value = "512Mi"
              }
            ]
            skipSchemaValidation = true
          }
        },
        {
          repoURL        = "https://istio-release.storage.googleapis.com/charts"
          chart          = "cni"
          path           = "."
          targetRevision = "1.27.3"
          helm = {
            releaseName          = "istio-cni"
            valueFiles           = ["$values/clusters/homelab/apps/istio/values.yaml"]
            skipSchemaValidation = true
          }
        },
        {
          repoURL        = "https://istio-release.storage.googleapis.com/charts"
          chart          = "ztunnel"
          path           = "."
          targetRevision = "1.27.3"
          helm = {
            releaseName = "ztunnel"
            valueFiles  = ["$values/clusters/homelab/apps/istio/values.yaml"]
            parameters = [
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
          repoURL        = "https://istio-release.storage.googleapis.com/charts"
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
          repoURL        = "https://istio-release.storage.googleapis.com/charts"
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
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/istio"
          targetRevision = local.target_revision
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
}

unit "argocd_apps_harbor" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/harbor"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "cert-manager", "istio", "platform-storage", "prometheus"]
    spec = {
      sources = [
        {
          repoURL        = "https://helm.goharbor.io"
          chart          = "harbor"
          path           = "."
          targetRevision = "1.19.2"
          helm = {
            releaseName = "harbor"
            valueFiles  = ["$values/clusters/homelab/apps/harbor/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/harbor"
          targetRevision = local.target_revision
        }
      ]
      syncPolicy = {
        retry = {
          limit = 5
          backoff = {
            factor      = 2
            maxDuration = "3m"
          }
        }
      }
      info = [
        {
          name  = "url"
          value = "https://harbor.stinkyboi.com"
        },
        {
          name  = "runbook"
          value = "clusters/homelab/apps/harbor/README.md"
        }
      ]
    }
  }
}

unit "argocd_apps_kiali" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/kiali"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["istio", "prometheus", "grafana"]
    spec = {
      destination = {
        namespace = "istio-system"
      }
      sources = [
        {
          repoURL        = "https://kiali.org/helm-charts"
          chart          = "kiali-operator"
          path           = "."
          targetRevision = "2.26.0"
          helm = {
            releaseName = "kiali-operator"
            valueFiles  = ["$values/clusters/homelab/apps/kiali/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/kiali"
          targetRevision = local.target_revision
        }
      ]
      info = [
        {
          name  = "ingress"
          value = "private app access is through the Octelium service catalog"
        },
        {
          name  = "auth"
          value = "anonymous read-only; Octelium service-proxy access through Istio is allowlisted"
        }
      ]
    }
  }
}

unit "argocd_apps_litellm" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/litellm"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "cert-manager", "istio", "platform-storage", "langfuse"]
    spec = {
      destination = {
        namespace = "ai"
      }
      sources = [
        {
          repoURL        = "ghcr.io/berriai"
          chart          = "litellm-helm"
          path           = "."
          targetRevision = "0.1.832"
          helm = {
            releaseName = "litellm"
            valueFiles  = ["$values/clusters/homelab/apps/litellm/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/litellm"
          targetRevision = local.target_revision
        }
      ]
      info = [
        {
          name  = "rollout"
          value = "automated; verify provider secrets and NFS backup coverage before exposing the gateway"
        }
      ]
    }
  }
}

unit "argocd_apps_langfuse" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/langfuse"
  no_dot_terragrunt_stack = true

  values = {
    defaults = local.argocd_defaults
    dependencies = [
      "../aws-ssm-parameters",
      "external-secrets",
      "cert-manager",
      "istio",
      "platform-storage",
      "../langfuse-blob-storage"
    ]
    spec = {
      sources = [
        {
          repoURL        = "ghcr.io/langfuse/langfuse-k8s/charts"
          chart          = "langfuse"
          path           = "."
          targetRevision = "2.1.1"
          helm = {
            releaseName = "langfuse"
            valueFiles  = ["$values/clusters/homelab/apps/langfuse/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/langfuse"
          targetRevision = local.target_revision
        }
      ]
      info = [
        {
          name  = "retention"
          value = "single-replica pilot; raw event bodies expire from S3 after 30 days"
        }
      ]
    }
  }
}

unit "argocd_apps_media_postgres" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/media-postgres"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "platform-storage"]
    spec = {
      destination = {
        namespace = "media"
      }
      ignoreDifferences = [
        {
          group        = "apps"
          kind         = "StatefulSet"
          name         = "media-postgres"
          namespace    = "media"
          jsonPointers = ["/metadata/annotations", "/spec/volumeClaimTemplates"]
        }
      ]
      info = [
        {
          name  = "rollout"
          value = "automated; replace the SSM password placeholder and verify PostgreSQL readiness before syncing media apps"
        },
        {
          name  = "storage"
          value = "docs/storage-nfs.md"
        }
      ]
    }
  }
}

unit "argocd_apps_metrics_server" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/metrics-server"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
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
}

unit "argocd_apps_multica" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/multica"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "cert-manager", "istio", "litellm", "platform-storage"]
    spec = {
      destination = {
        namespace = "ai"
      }
      sources = [
        {
          repoURL        = "ghcr.io/multica-ai/charts"
          chart          = "multica"
          path           = "."
          targetRevision = "0.4.29"
          helm = {
            releaseName = "multica"
            valueFiles  = ["$values/clusters/homelab/apps/multica/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/multica"
          targetRevision = local.target_revision
        }
      ]
      syncPolicy = {
        retry = {
          backoff = {
            maxDuration = "3m"
          }
        }
      }
      info = [
        {
          name  = "url"
          value = "https://multica.stinkyboi.com"
        },
        {
          name  = "rollout"
          value = "automated after generated SSM secrets, External Secrets, pgvector PostgreSQL, NFS, Istio, and Octelium are healthy"
        },
        {
          name  = "storage"
          value = "docs/storage-nfs.md"
        }
      ]
    }
  }
}

unit "argocd_apps_nofx" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/nofx"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "istio", "octelium", "litellm", "platform-storage"]
    spec = {
      syncPolicy = {
        retry = {
          backoff = {
            maxDuration = "3m"
          }
        }
      }
      info = [
        {
          name  = "url"
          value = "https://nofx.stinkyboi.com"
        },
        {
          name  = "rollout"
          value = "automated after generated SSM secrets, External Secrets, NFS, Istio, and Octelium are healthy"
        },
        {
          name  = "storage"
          value = "docs/storage-nfs.md"
        }
      ]
    }
  }
}

unit "argocd_apps_n8n" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/n8n"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "cert-manager", "istio", "platform-storage", "n8n-postgres"]
    spec = {
      destination = {
        namespace = "automation"
      }
      sources = [
        {
          repoURL        = "https://bjw-s-labs.github.io/helm-charts"
          chart          = "app-template"
          path           = "."
          targetRevision = "4.4.0"
          helm = {
            releaseName = "n8n"
            valueFiles  = ["$values/clusters/homelab/apps/n8n/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/n8n"
          targetRevision = local.target_revision
        }
      ]
      info = [
        {
          name  = "rollout"
          value = "automated; preserve the instance encryption key on the n8n PVC and verify n8n-postgres plus NFS backup coverage before relying on automation history"
        }
      ]
    }
  }
}

unit "argocd_apps_n8n_postgres" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/n8n-postgres"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "platform-storage"]
    spec = {
      destination = {
        namespace = "automation"
      }
      syncPolicy = {
        managedNamespaceMetadata = {
          labels = {
            "app.kubernetes.io/name"                     = "automation"
            "app.kubernetes.io/part-of"                  = "homelab"
            "istio.io/dataplane-mode"                    = "ambient"
            "pod-security.kubernetes.io/audit"           = "restricted"
            "pod-security.kubernetes.io/audit-version"   = "latest"
            "pod-security.kubernetes.io/enforce"         = "baseline"
            "pod-security.kubernetes.io/enforce-version" = "latest"
            "pod-security.kubernetes.io/warn"            = "restricted"
            "pod-security.kubernetes.io/warn-version"    = "latest"
          }
          annotations = {}
        }
      }
      ignoreDifferences = [
        {
          group        = "apps"
          kind         = "StatefulSet"
          name         = "n8n-postgres"
          namespace    = "automation"
          jsonPointers = ["/metadata/annotations", "/spec/volumeClaimTemplates"]
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

unit "argocd_apps_octelium" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "istio"]
    spec = {
      destination = {
        namespace = "octelium-client"
      }
      info = [
        {
          name  = "mode"
          value = "Octelium service catalog is the homelab app access path; app FQDNs use private Istio SNI backend routes"
        },
        {
          name  = "services"
          value = "Serves the explicit homelab service catalog in docs/examples/octelium"
        },
        {
          name  = "enterprise"
          value = "Enterprise package octeliumee desired version 0.22.0 is adopted by the octelium-enterprise Argo CD Application"
        },
        {
          name  = "state"
          value = "Stateless connector plus in-cluster demo service"
        }
      ]
    }
  }
}

unit "argocd_apps_octelium_cluster" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-cluster"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["istio", "platform-multus", "octelium-storage"]
    spec = {
      destination = {
        namespace = "istio-system"
      }
      syncPolicy = {
        automated = {
          prune = false
        }
        syncOptions = ["CreateNamespace=false", "ServerSideApply=true"]
      }
      info = [
        {
          name  = "bootstrap"
          value = "Run scripts/octelium-cluster-bootstrap.sh after platform-multus and octelium-storage are healthy"
        }
      ]
    }
  }
}

unit "argocd_apps_octelium_enterprise" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-enterprise"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["octelium-cluster", "octelium-storage"]
    spec = {
      destination = {
        namespace = "octelium"
      }
      syncPolicy = {
        syncOptions = ["CreateNamespace=false", "ServerSideApply=true", "RespectIgnoreDifferences=true"]
      }
      ignoreDifferences = [
        {
          group     = "apps"
          kind      = "Deployment"
          name      = "svc-console-octelium"
          namespace = "octelium"
          jqPathExpressions = [
            ".spec.template.spec.containers[] | select(.name == \"vigil\" or .name == \"managed\") | .image"
          ]
        },
        {
          group     = "apps"
          kind      = "Deployment"
          name      = "svc-dirsync-octelium"
          namespace = "octelium"
          jqPathExpressions = [
            ".spec.template.spec.containers[] | select(.name == \"vigil\" or .name == \"managed\") | .image"
          ]
        },
        {
          group     = "apps"
          kind      = "Deployment"
          name      = "svc-enterprise-octelium-api"
          namespace = "octelium"
          jqPathExpressions = [
            ".spec.template.spec.containers[] | select(.name == \"vigil\" or .name == \"managed\") | .image"
          ]
        },
        {
          group     = "apps"
          kind      = "Deployment"
          name      = "svc-public-octelium"
          namespace = "octelium"
          jqPathExpressions = [
            ".spec.template.spec.containers[] | select(.name == \"vigil\" or .name == \"managed\") | .image"
          ]
        }
      ]
      info = [
        {
          name  = "package"
          value = "Octelium Enterprise package octeliumee 0.22.0"
        },
        {
          name  = "ownership"
          value = "Argo CD owns the package Kubernetes steady state after octops installation"
        },
        {
          name  = "state"
          value = "Enterprise stores use octelium-rscstore, octelium-logstore, and octelium-metricstore PVCs"
        }
      ]
    }
  }
}

unit "argocd_apps_octelium_public" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-public"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "istio", "octelium-cluster"]
  }
}

unit "argocd_apps_octelium_storage" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-storage"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "platform-storage"]
    spec = {
      ignoreDifferences = [
        {
          group        = "apps"
          kind         = "StatefulSet"
          name         = "octelium-postgres"
          namespace    = "octelium-storage"
          jsonPointers = ["/metadata/annotations", "/spec/volumeClaimTemplates"]
        },
        {
          group        = "apps"
          kind         = "StatefulSet"
          name         = "octelium-redis"
          namespace    = "octelium-storage"
          jsonPointers = ["/metadata/annotations", "/spec/volumeClaimTemplates"]
        }
      ]
      info = [
        {
          name  = "state"
          value = "PostgreSQL and Redis backing stores for octops init"
        }
      ]
    }
  }
}

unit "argocd_apps_octobot" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octobot"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["cert-manager", "istio", "platform-storage"]
    spec = {
      destination = {
        namespace = "finance"
      }
      sources = [
        {
          repoURL        = "https://bjw-s-labs.github.io/helm-charts"
          chart          = "app-template"
          path           = "."
          targetRevision = "4.4.0"
          helm = {
            releaseName = "octobot"
            valueFiles  = ["$values/clusters/homelab/apps/octobot/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/octobot"
          targetRevision = local.target_revision
        }
      ]
      info = [
        {
          name  = "rollout"
          value = "OctoBot UI targets octobot.homelab via Octelium; no exchange credentials, real-trading strategy, or autostart configuration are committed"
        }
      ]
    }
  }
}

unit "argocd_apps_openclaw" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/openclaw"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "cert-manager", "istio", "litellm", "platform-storage"]
    spec = {
      project = "homelab-workloads"
      destination = {
        namespace = "ai"
      }
      sources = [
        {
          repoURL        = "https://bjw-s-labs.github.io/helm-charts"
          chart          = "app-template"
          path           = "."
          targetRevision = "4.4.0"
          helm = {
            releaseName = "openclaw"
            valueFiles  = ["$values/clusters/homelab/apps/openclaw/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/openclaw"
          targetRevision = local.target_revision
        }
      ]
      info = [
        {
          name  = "rollout"
          value = "automated; verify LiteLLM and NFS backup coverage before relying on runtime state"
        }
      ]
    }
  }
}

unit "argocd_apps_platform_crossplane" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-crossplane"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = []
    spec = {
      destination = {
        namespace = "crossplane-system"
      }
      sources = [
        {
          repoURL        = "https://charts.crossplane.io/stable"
          chart          = "crossplane"
          path           = "."
          targetRevision = "2.3.3"
          helm = {
            releaseName = "crossplane"
          }
        }
      ]
      syncPolicy = {
        syncOptions = ["CreateNamespace=true", "ServerSideApply=true", "SkipDryRunOnMissingResource=true"]
      }
      info = [
        {
          name  = "rollout"
          value = "core only; add providers and credentials in purpose-specific changes"
        },
        {
          name  = "docs"
          value = "clusters/homelab/platform/crossplane/README.md"
        }
      ]
    }
  }
}

unit "argocd_apps_platform_dns" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-dns"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = []
    spec = {
      destination = {
        namespace = "kube-system"
      }
      sources = [
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/platform/dns"
          targetRevision = local.target_revision
        }
      ]
      syncPolicy = {
        automated = {
          prune = false
        }
        syncOptions = ["CreateNamespace=false"]
      }
      info = [
        {
          name  = "dns"
          value = "clusters/homelab/platform/dns/README.md"
        },
        {
          name  = "prune"
          value = "disabled because this app adopts all six bootstrap CoreDNS resources"
        }
      ]
    }
  }
}

unit "argocd_apps_platform_multus" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-multus"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = []
    spec = {
      destination = {
        namespace = "kube-system"
      }
      sources = [
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/platform/multus"
          targetRevision = local.target_revision
        }
      ]
      syncPolicy = {
        syncOptions = ["ServerSideApply=true"]
      }
      info = [
        {
          name  = "platform"
          value = "Talos-compatible Multus thick CNI for Octelium data-plane workloads"
        }
      ]
    }
  }
}

unit "argocd_apps_platform_storage" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-storage"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = []
    spec = {
      destination = {
        namespace = "kube-system"
      }
      sources = [
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/platform/storage"
          targetRevision = local.target_revision
        }
      ]
      syncPolicy = {
        syncOptions = ["CreateNamespace=false"]
      }
      info = [
        {
          name  = "rollout"
          value = "automated; verify existing NFS provisioner and backup coverage before relying on PVCs"
        },
        {
          name  = "storage"
          value = "docs/storage-nfs.md"
        }
      ]
    }
  }
}

unit "argocd_apps_policy_bot" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/policy-bot"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "cert-manager", "istio"]
    spec = {
      project = "homelab-workloads"
      destination = {
        namespace = "automation"
      }
      info = [
        {
          name  = "public-webhook"
          value = "Policy Bot UI targets policy-bot.homelab via Octelium; /api/github/hook uses policy-bot-hook.stinkyboi.com through octelium-public"
        }
      ]
    }
  }
}

unit "argocd_apps_prometheus" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/prometheus"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets", "platform-storage"]
    spec = {
      destination = {
        namespace = "monitoring"
      }
      sources = [
        {
          repoURL        = "https://prometheus-community.github.io/helm-charts"
          chart          = "kube-prometheus-stack"
          path           = "."
          targetRevision = "85.2.0"
          helm = {
            releaseName = "prometheus"
            valueFiles  = ["$values/clusters/homelab/apps/prometheus/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/prometheus"
          targetRevision = local.target_revision
        }
      ]
      info = [
        {
          name  = "rollout"
          value = "automated; verify NFS backup coverage before relying on retained metrics"
        },
        {
          name  = "storage"
          value = "docs/storage-nfs.md"
        }
      ]
    }
  }
}

unit "argocd_apps_prowlarr" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/prowlarr"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["cert-manager", "istio", "media-postgres", "platform-storage"]
    spec = {
      project = "homelab-workloads"
      destination = {
        namespace = "media"
      }
      sources = [
        {
          repoURL        = "https://bjw-s-labs.github.io/helm-charts"
          chart          = "app-template"
          path           = "."
          targetRevision = "4.4.0"
          helm = {
            releaseName = "prowlarr"
            valueFiles  = ["$values/clusters/homelab/apps/prowlarr/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/prowlarr"
          targetRevision = local.target_revision
        }
      ]
      info = [
        {
          name  = "rollout"
          value = "automated; configure indexers and app integrations after first login, then verify NFS backup coverage"
        }
      ]
    }
  }
}

unit "argocd_apps_radarr" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/radarr"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["cert-manager", "istio", "deluge", "media-postgres", "prowlarr", "platform-storage"]
    spec = {
      destination = {
        namespace = "media"
      }
      sources = [
        {
          repoURL        = "https://bjw-s-labs.github.io/helm-charts"
          chart          = "app-template"
          path           = "."
          targetRevision = "4.4.0"
          helm = {
            releaseName = "radarr"
            valueFiles  = ["$values/clusters/homelab/apps/radarr/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/radarr"
          targetRevision = local.target_revision
        }
      ]
      info = [
        {
          name  = "rollout"
          value = "automated; verify Deluge, Prowlarr, and NFS backup coverage before relying on media automation"
        }
      ]
    }
  }
}

unit "argocd_apps_sonarr" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/sonarr"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["cert-manager", "istio", "deluge", "media-postgres", "prowlarr", "platform-storage"]
    spec = {
      destination = {
        namespace = "media"
      }
      sources = [
        {
          repoURL        = "https://bjw-s-labs.github.io/helm-charts"
          chart          = "app-template"
          path           = "."
          targetRevision = "4.4.0"
          helm = {
            releaseName = "sonarr"
            valueFiles  = ["$values/clusters/homelab/apps/sonarr/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/sonarr"
          targetRevision = local.target_revision
        }
      ]
      info = [
        {
          name  = "rollout"
          value = "automated; verify Deluge, Prowlarr, and NFS backup coverage before relying on media automation"
        }
      ]
    }
  }
}

unit "argocd_apps_tailscale" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/tailscale"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets"]
    spec = {
      sources = [
        {
          repoURL        = "https://pkgs.tailscale.com/helmcharts"
          chart          = "tailscale-operator"
          path           = "."
          targetRevision = "1.102.3"
          helm = {
            releaseName = "tailscale-operator"
            valueFiles  = ["$values/clusters/homelab/apps/tailscale/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          path           = "."
          targetRevision = local.target_revision
          ref            = "values"
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          path           = "clusters/homelab/apps/tailscale"
          targetRevision = local.target_revision
        }
      ]
    }
  }
}

unit "argocd_apps_wazuh" {
  # Preserve the encrypted state address while the scoped retirement is applied.
  source                  = "./.catalog/units/live/retired-argocd-app"
  path                    = "live/argocd-apps/wazuh"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = []
  }
}

unit "aws_ssm_parameters" {
  source                  = "./.catalog/units/live/aws-ssm-parameters"
  path                    = "live/aws-ssm-parameters"
  no_dot_terragrunt_stack = true
}

unit "langfuse_blob_storage" {
  source                  = "./.catalog/units/live/langfuse-blob-storage"
  path                    = "live/langfuse-blob-storage"
  no_dot_terragrunt_stack = true
}

unit "azuread_applications_fleet" {
  source                  = "./.catalog/units/live/azuread-applications/fleet"
  path                    = "live/azuread-applications/fleet"
  no_dot_terragrunt_stack = true
}

# A cloud-only device user; placed here to use the existing AzureAD CI scope.
unit "azuread_fleet_pilot_user" {
  source                  = "./.catalog/units/live/azuread-applications/fleet-pilot-user"
  path                    = "live/azuread-applications/fleet-pilot-user"
  no_dot_terragrunt_stack = true
}

unit "azuread_applications_grafana" {
  source                  = "./.catalog/units/live/azuread-applications/grafana"
  path                    = "live/azuread-applications/grafana"
  no_dot_terragrunt_stack = true
}

unit "azuread_applications_octelium" {
  source                  = "./.catalog/units/live/azuread-applications/octelium"
  path                    = "live/azuread-applications/octelium"
  no_dot_terragrunt_stack = true
}

unit "kubernetes_node_labels" {
  source                  = "./.catalog/units/live/kubernetes-node-labels"
  path                    = "live/kubernetes-node-labels"
  no_dot_terragrunt_stack = true
}

unit "kubernetes_secrets_external_secrets_aws_ssm_auth" {
  source                  = "./.catalog/units/live/kubernetes-secrets/external-secrets-aws-ssm-auth"
  path                    = "live/kubernetes-secrets/external-secrets-aws-ssm-auth"
  no_dot_terragrunt_stack = true
}

unit "operator_github_actions_role_policy" {
  source                  = "./.catalog/units/operator/github-actions-role-policy"
  path                    = "operator/github-actions-role-policy"
  no_dot_terragrunt_stack = true
}

unit "operator_state_bucket_encryption" {
  source                  = "./.catalog/units/operator/state-bucket-encryption"
  path                    = "operator/state-bucket-encryption"
  no_dot_terragrunt_stack = true
}

unit "operator_legacy_kms_retirement" {
  source                  = "./.catalog/units/operator/legacy-kms-retirement"
  path                    = "operator/legacy-kms-retirement"
  no_dot_terragrunt_stack = true
}

unit "operator_etcd_backup_storage" {
  source                  = "./.catalog/units/operator/etcd-backup-storage"
  path                    = "operator/etcd-backup-storage"
  no_dot_terragrunt_stack = true
}

unit "operator_azuread_ci_identities" {
  source                  = "./.catalog/units/operator/azuread-ci-identities"
  path                    = "operator/azuread-ci-identities"
  no_dot_terragrunt_stack = true
}

# Read and verify a non-default managed Entra domain before creating the one
# scoped cloud-only Mac pilot. These operator units never modify Google users.
unit "operator_entra_stuhlmuller_domain" {
  source                  = "./.catalog/units/operator/entra-stuhlmuller-domain"
  path                    = "operator/entra-stuhlmuller-domain"
  no_dot_terragrunt_stack = true
}

unit "operator_entra_stuhlmuller_pilot_user" {
  source                  = "./.catalog/units/operator/entra-stuhlmuller-pilot-user"
  path                    = "operator/entra-stuhlmuller-pilot-user"
  no_dot_terragrunt_stack = true
}
