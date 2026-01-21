resource "kubernetes_namespace_v1" "argocd" {
  metadata {
    name = "argocd"
    labels = {
      "name" = "argocd"
    }
  }
}

resource "helm_release" "release" {
  name       = "argocd"
  chart      = "argo-cd"
  repository = "https://argoproj.github.io/argo-helm"
  version    = "9.3.4"
  timeout    = "1500"
  namespace  = kubernetes_namespace_v1.argocd.metadata[0].name

  values = [yamlencode({
    global = {
      domain                   = "argocd.stinkyboi.com"
      addPrometheusAnnotations = "false"
      env = [
        {
          name = "dex.azure.clientSecret"
          valueFrom = {
            secretKeyRef = {
              name = "dex-oidc-secret"
              key  = "client_secret"
            }
          }
        }
      ]
    }
    image = {
      pullPolicy = "Always"
    }
    applicationSet = {
      metrics = {
        enabled = true
        serviceMonitor = {
          enabled = true
          selector = {
            release = "prometheus"
          }
          additionalLabels = {
            release = "prometheus"
          }
        }
      }
    }
    controller = {
      metrics = {
        enabled = true
        serviceMonitor = {
          enabled = true
          selector = {
            release = "prometheus"
          }
          additionalLabels = {
            release = "prometheus"
          }
        }
      }
    }
    repoServer = {
      metrics = {
        enabled = true
        serviceMonitor = {
          enabled = true
          selector = {
            release = "prometheus"
          }
          additionalLabels = {
            release = "prometheus"
          }
        }
      }
    }
    notifications = {
      metrics = {
        enabled = true
        serviceMonitor = {
          enabled = true
          selector = {
            release = "prometheus"
          }
          additionalLabels = {
            release = "prometheus"
          }
        }
      }
    }
    server = {
      metrics = {
        enabled = true
        serviceMonitor = {
          enabled = true
          selector = {
            release = "prometheus"
          }
          additionalLabels = {
            release = "prometheus"
          }
        }
      }
      certificate = {
        enabled    = true
        secretName = "argocd-server-tls"
        issuer = {
          group = "cert-manager.io"
          kind  = "ClusterIssuer"
          name  = "cloudflare-clusterissuer"
        }
      }
      ingress = {
        enabled          = true
        ingressClassName = "traefik"
        tls              = true
        annotations = {
          "traefik.ingress.kubernetes.io/router.entrypoints" = "websecure"
        }
      }
    }
    configs = {
      params = {
        "server.insecure" = "true"
      }
      secret = {
        createSecret = true
      }
      rbac = {
        create           = true
        "policy.default" = "role:admin"
        "policy.csv"     = <<EOF
p, app_user, *, *, *, allow
EOF
      }
      cm = {
        "accounts.app_user"         = "apiKey"
        "accounts.app_user.enabled" = true
        "dex.config" = yamlencode({
          connectors = [{
            type = "microsoft"
            id   = "microsoft"
            name = "Azure"
            config = {
              clientID     = "5dd3e953-5c5d-4854-b284-a9f1fd0d00fa" # `ArgoCD` azure app
              clientSecret = "$${dex.azure.clientSecret}"
              redirectURI  = "https://argocd.stinkyboi.com/api/dex/callback"
              tenant       = "2aee152b-5281-40d0-8f4b-60faf40514ab"
            }
          }]
        })
      }
    }
  })]
}

resource "helm_release" "argocd_image_updater" {
  name       = "argocd-image-updater"
  chart      = "argocd-image-updater"
  repository = "https://argoproj.github.io/argo-helm"
  version    = "1.0.4"
  namespace  = kubernetes_namespace_v1.argocd.metadata[0].name
  wait       = true
}

resource "kubernetes_manifest" "argocd_certificate" {
  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "Certificate"
    metadata = {
      name      = "argocd"
      namespace = kubernetes_namespace_v1.argocd.metadata[0].name
    }
    spec = {
      secretName = "argocd-server-tls"
      issuerRef = {
        name = "cloudflare-clusterissuer"
        kind = "ClusterIssuer"
      }
      dnsNames = [
        "argocd.stinkyboi.com"
      ]
    }
  }
}

resource "aws_ssm_parameter" "argocd" {
  #checkov:skip=CKV_AWS_337: Need to update with project key
  for_each = toset(["client_secret"])
  name     = lower("/homelab/argocd/${each.value}")
  type     = "SecureString"
  value    = "update_me"

  lifecycle {
    ignore_changes  = [value]
    prevent_destroy = true
  }
}

resource "kubernetes_manifest" "argocd_secret" {
  manifest = {
    apiVersion = "external-secrets.io/v1"
    kind       = "ExternalSecret"
    metadata = {
      name      = "dex-oidc-secret"
      namespace = kubernetes_namespace_v1.argocd.metadata[0].name
    }
    spec = {
      secretStoreRef = {
        name = "parameterstore"
        kind = "ClusterSecretStore"
      }
      refreshPolicy = "OnChange"
      data = [for key, value in aws_ssm_parameter.argocd : {
        secretKey = key
        remoteRef = {
          key = value.name
        }
      }]
    }
  }
}
