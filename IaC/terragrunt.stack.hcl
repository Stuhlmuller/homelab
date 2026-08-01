locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
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
    dependencies = [
      "external-secrets",
      "cert-manager",
      "istio",
      "octelium",
      "octelium-public",
      "platform-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "affine"
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
          namespace = "affine"
        }

        sources = [
          {
            repoURL        = local.repo_url
            targetRevision = local.target_revision
            path           = "clusters/homelab/apps/affine"
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
              maxDuration = "3m"
            }
          }
        }

        ignoreDifferences = [
          {
            group     = "apps"
            kind      = "StatefulSet"
            name      = "affine-postgres"
            namespace = "affine"
            jsonPointers = [
              "/metadata/annotations",
              "/spec/volumeClaimTemplates"
            ]
          },
          {
            group     = "apps"
            kind      = "StatefulSet"
            name      = "affine-redis"
            namespace = "affine"
            jsonPointers = [
              "/metadata/annotations",
              "/spec/volumeClaimTemplates"
            ]
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
}

unit "argocd_apps_argocd_image_updater" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/argocd-image-updater"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = ["external-secrets"]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "argocd-image-updater"
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
          namespace = "argocd"
        }

        sources = [
          {
            repoURL        = "https://argoproj.github.io/argo-helm"
            chart          = "argocd-image-updater"
            path           = "."
            targetRevision = "1.2.2"
            helm = {
              releaseName = "argocd-image-updater"
              valueFiles  = ["$values/clusters/homelab/apps/argocd-image-updater/values.yaml"]
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
            path           = "clusters/homelab/apps/argocd-image-updater"
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

        info = [
          {
            name  = "image-updates"
            value = "docs/argocd-image-updater.md"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_cert_manager" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/cert-manager"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = ["external-secrets"]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "cert-manager"
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
          namespace = "cert-manager"
        }

        sources = [
          {
            repoURL        = "https://charts.jetstack.io"
            chart          = "cert-manager"
            path           = "."
            targetRevision = "v1.19.2"
            helm = {
              releaseName = "cert-manager"
              valueFiles  = ["$values/clusters/homelab/apps/cert-manager/values.yaml"]
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
            path           = "clusters/homelab/apps/cert-manager"
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
      }
    }
  }
}

unit "argocd_apps_compass" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/compass"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "cert-manager",
      "istio",
      "prometheus"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "compass"
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
            path           = "clusters/homelab/apps/compass"
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
}

unit "argocd_apps_cordium" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/cordium"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "octelium-cluster",
      "octelium-enterprise"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "cordium"
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
          namespace = "octelium"
        }

        sources = [
          {
            repoURL        = local.repo_url
            targetRevision = local.target_revision
            path           = "clusters/homelab/apps/cordium"
            kustomize      = {}
          }
        ]

        syncPolicy = {
          automated = {
            allowEmpty = false
            enabled    = true
            prune      = false
            selfHeal   = true
          }
          syncOptions = [
            "CreateNamespace=false",
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
}

unit "argocd_apps_deluge" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/deluge"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "cert-manager",
      "istio",
      "platform-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "deluge"
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
            path           = "clusters/homelab/apps/deluge"
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

        info = [
          {
            name  = "rollout"
            value = "automated; verify NFS backup coverage before relying on downloads"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_descheduler" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/descheduler"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = ["prometheus"]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "descheduler"
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
            targetRevision = local.target_revision
            ref            = "values"
            path           = "."
            directory = {
              include = ".argocd-values-ref-placeholder.yaml"
            }
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
      }
    }
  }
}

unit "argocd_apps_dispatcharr" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/dispatcharr"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "cert-manager",
      "istio",
      "platform-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "dispatcharr"
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
            path           = "clusters/homelab/apps/dispatcharr"
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

        info = [
          {
            name  = "rollout"
            value = "automated; uses dedicated PostgreSQL plus in-pod Redis; complete first-run IPTV source and admin setup through the Octelium-protected UI"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_external_secrets" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/external-secrets"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = ["platform-dns"]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "external-secrets"
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
          namespace = "external-secrets"
        }

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
            path           = "clusters/homelab/apps/external-secrets"
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

        info = [
          {
            name  = "secrets"
            value = "docs/secrets-aws-ssm.md"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_github_actions_runner" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/github-actions-runner"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = []
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "github-actions-runner"
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
          namespace = "github-actions-runner"
        }

        sources = [
          {
            repoURL        = local.repo_url
            targetRevision = local.target_revision
            path           = "clusters/homelab/apps/github-actions-runner"
            kustomize      = {}
          }
        ]

        syncPolicy = {
          automated = {
            allowEmpty = true
            enabled    = true
            prune      = true
            selfHeal   = true
          }
          syncOptions = [
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
      }
    }
  }
}

unit "argocd_apps_grafana" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/grafana"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "cert-manager",
      "istio",
      "prometheus",
      "platform-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "grafana"
        namespace = "argocd"
        annotations = {
          "argocd.argoproj.io/refresh" = "hard"
        }
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
          namespace = "monitoring"
        }

        sources = [
          {
            repoURL        = "https://grafana.github.io/helm-charts"
            chart          = "grafana"
            path           = "."
            targetRevision = "10.5.15"
            helm = {
              releaseName = "grafana"
              valueFiles  = ["$values/clusters/homelab/apps/grafana/values.yaml"]
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
            path           = "clusters/homelab/apps/grafana"
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
}

unit "argocd_apps_grafana_alert_cleanup" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/grafana-alert-cleanup"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "istio"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "grafana-alert-cleanup"
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
          namespace = "monitoring"
        }

        sources = [
          {
            repoURL        = local.repo_url
            targetRevision = local.target_revision
            path           = "clusters/homelab/apps/grafana-alert-cleanup"
            kustomize      = {}
          }
        ]

        syncPolicy = {
          automated = {
            allowEmpty = true
            enabled    = true
            prune      = true
            selfHeal   = true
          }
          syncOptions = [
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

        info = [
          {
            name  = "purpose"
            value = "retirement tombstone that prunes the completed Grafana alert cleanup resources"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_istio" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/istio"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = ["cert-manager"]
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
            repoURL        = "https://istio-release.storage.googleapis.com/charts"
            chart          = "gateway"
            path           = "."
            targetRevision = "1.27.3"
            helm = {
              releaseName          = "octelium-api-ingressgateway"
              skipSchemaValidation = true
              valueFiles           = ["$values/clusters/homelab/apps/istio/octelium-api-gateway-values.yaml"]
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
}

unit "argocd_apps_kiali" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/kiali"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "istio",
      "prometheus",
      "grafana"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "kiali"
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
            path           = "clusters/homelab/apps/kiali"
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
}

unit "argocd_apps_litellm" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/litellm"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "cert-manager",
      "istio",
      "platform-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "litellm"
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
            path           = "clusters/homelab/apps/litellm"
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

        info = [
          {
            name  = "rollout"
            value = "automated; verify provider secrets and NFS backup coverage before exposing the gateway"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_media_postgres" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/media-postgres"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "platform-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "media-postgres"
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
          namespace = "media"
        }

        sources = [
          {
            repoURL        = local.repo_url
            targetRevision = local.target_revision
            path           = "clusters/homelab/apps/media-postgres"
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
            group     = "apps"
            kind      = "StatefulSet"
            name      = "media-postgres"
            namespace = "media"
            jsonPointers = [
              "/metadata/annotations",
              "/spec/volumeClaimTemplates"
            ]
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
}

unit "argocd_apps_n8n" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/n8n"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "cert-manager",
      "istio",
      "platform-storage",
      "n8n-postgres"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "n8n"
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
            path           = "clusters/homelab/apps/n8n"
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

        info = [
          {
            name  = "rollout"
            value = "automated; update the n8n encryption key before storing real credentials and verify n8n-postgres plus NFS backup coverage before relying on automation history"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_n8n_postgres" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/n8n-postgres"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "platform-storage"
    ]
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
            repoURL        = local.repo_url
            targetRevision = local.target_revision
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
}

unit "argocd_apps_octelium" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "istio"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "octelium"
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
          namespace = "octelium-client"
        }

        sources = [
          {
            repoURL        = local.repo_url
            targetRevision = local.target_revision
            path           = "clusters/homelab/apps/octelium"
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
}

unit "argocd_apps_octelium_cluster" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-cluster"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "istio",
      "platform-multus",
      "octelium-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "octelium-cluster"
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
            repoURL        = local.repo_url
            targetRevision = local.target_revision
            path           = "clusters/homelab/apps/octelium-cluster"
            kustomize      = {}
          }
        ]

        syncPolicy = {
          automated = {
            allowEmpty = false
            enabled    = true
            prune      = false
            selfHeal   = true
          }
          syncOptions = [
            "CreateNamespace=false",
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

        info = [
          {
            name  = "bootstrap"
            value = "Run scripts/octelium-cluster-bootstrap.sh after platform-multus and octelium-storage are healthy"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_octelium_enterprise" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-enterprise"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "octelium-cluster",
      "octelium-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "octelium-enterprise"
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
          namespace = "octelium"
        }

        sources = [
          {
            repoURL        = local.repo_url
            targetRevision = local.target_revision
            path           = "clusters/homelab/apps/octelium-enterprise"
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
            "CreateNamespace=false",
            "ServerSideApply=true",
            "RespectIgnoreDifferences=true"
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
}

unit "argocd_apps_octelium_public" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-public"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "istio",
      "octelium-cluster"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "octelium-public"
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
          namespace = "octelium-public"
        }

        sources = [
          {
            repoURL        = local.repo_url
            targetRevision = local.target_revision
            path           = "clusters/homelab/apps/octelium-public"
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
      }
    }
  }
}

unit "argocd_apps_octelium_storage" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-storage"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "platform-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "octelium-storage"
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
          namespace = "octelium-storage"
        }

        sources = [
          {
            repoURL        = local.repo_url
            targetRevision = local.target_revision
            path           = "clusters/homelab/apps/octelium-storage"
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
            group     = "apps"
            kind      = "StatefulSet"
            name      = "octelium-postgres"
            namespace = "octelium-storage"
            jsonPointers = [
              "/metadata/annotations",
              "/spec/volumeClaimTemplates"
            ]
          },
          {
            group     = "apps"
            kind      = "StatefulSet"
            name      = "octelium-redis"
            namespace = "octelium-storage"
            jsonPointers = [
              "/metadata/annotations",
              "/spec/volumeClaimTemplates"
            ]
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
}

unit "argocd_apps_octobot" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octobot"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "cert-manager",
      "istio",
      "platform-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "octobot"
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
            path           = "clusters/homelab/apps/octobot"
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

        info = [
          {
            name  = "rollout"
            value = "OctoBot UI targets octobot.homelab via Octelium; no exchange credentials, real-trading strategy, or autostart configuration are committed"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_openclaw" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/openclaw"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "cert-manager",
      "istio",
      "litellm",
      "platform-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "openclaw"
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
            path           = "clusters/homelab/apps/openclaw"
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

        info = [
          {
            name  = "rollout"
            value = "automated; verify LiteLLM and NFS backup coverage before relying on runtime state"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_platform_dns" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-dns"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = []
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "platform-dns"
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
          namespace = "kube-system"
        }

        sources = [
          {
            repoURL        = local.repo_url
            targetRevision = local.target_revision
            path           = "clusters/homelab/platform/dns"
            kustomize      = {}
          }
        ]

        syncPolicy = {
          automated = {
            allowEmpty = false
            enabled    = true
            prune      = false
            selfHeal   = true
          }
          syncOptions = [
            "CreateNamespace=false"
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

        info = [
          {
            name  = "dns"
            value = "clusters/homelab/platform/dns/README.md"
          },
          {
            name  = "prune"
            value = "disabled because this app adopts the bootstrap CoreDNS ConfigMap"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_platform_multus" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-multus"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = []
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "platform-multus"
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
          namespace = "kube-system"
        }

        sources = [
          {
            repoURL        = local.repo_url
            targetRevision = local.target_revision
            path           = "clusters/homelab/platform/multus"
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

        info = [
          {
            name  = "platform"
            value = "Talos-compatible Multus thick CNI for Octelium data-plane workloads"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_platform_storage" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-storage"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = []
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "platform-storage"
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
          namespace = "kube-system"
        }

        sources = [
          {
            repoURL        = local.repo_url
            targetRevision = local.target_revision
            path           = "clusters/homelab/platform/storage"
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
            "CreateNamespace=false"
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
}

unit "argocd_apps_policy_bot" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/policy-bot"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "cert-manager",
      "istio"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "policy-bot"
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
            repoURL        = local.repo_url
            targetRevision = local.target_revision
            path           = "clusters/homelab/apps/policy-bot"
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

        info = [
          {
            name  = "public-webhook"
            value = "Policy Bot UI targets policy-bot.homelab via Octelium; /api/github/hook uses policy-bot-hook.stinkyboi.com through octelium-public"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_prometheus" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/prometheus"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "platform-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "prometheus"
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
            path           = "clusters/homelab/apps/prometheus"
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
}

unit "argocd_apps_prowlarr" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/prowlarr"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "cert-manager",
      "istio",
      "media-postgres",
      "platform-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "prowlarr"
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
            path           = "clusters/homelab/apps/prowlarr"
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

        info = [
          {
            name  = "rollout"
            value = "automated; configure indexers and app integrations after first login, then verify NFS backup coverage"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_radarr" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/radarr"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "cert-manager",
      "istio",
      "deluge",
      "media-postgres",
      "prowlarr",
      "platform-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "radarr"
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
            path           = "clusters/homelab/apps/radarr"
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

        info = [
          {
            name  = "rollout"
            value = "automated; verify Deluge, Prowlarr, and NFS backup coverage before relying on media automation"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_sonarr" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/sonarr"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "cert-manager",
      "istio",
      "deluge",
      "media-postgres",
      "prowlarr",
      "platform-storage"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "sonarr"
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
            path           = "clusters/homelab/apps/sonarr"
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

        info = [
          {
            name  = "rollout"
            value = "automated; verify Deluge, Prowlarr, and NFS backup coverage before relying on media automation"
          }
        ]
      }
    }
  }
}

unit "argocd_apps_tailscale" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/tailscale"
  no_dot_terragrunt_stack = true

  values = {
    dependencies = [
      "external-secrets",
      "istio"
    ]
    manifest = {
      apiVersion = "argoproj.io/v1alpha1"
      kind       = "Application"

      metadata = {
        name      = "tailscale"
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
          namespace = "tailscale"
        }

        sources = [
          {
            repoURL        = "https://pkgs.tailscale.com/helmcharts"
            chart          = "tailscale-operator"
            path           = "."
            targetRevision = "1.98.3"
            helm = {
              releaseName = "tailscale-operator"
              valueFiles  = ["$values/clusters/homelab/apps/tailscale/values.yaml"]
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
            path           = "clusters/homelab/apps/tailscale"
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
      }
    }
  }
}

unit "aws_ssm_parameters" {
  source                  = "./.catalog/units/live/aws-ssm-parameters"
  path                    = "live/aws-ssm-parameters"
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
