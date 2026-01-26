resource "kubernetes_namespace_v1" "octobot" {
  metadata {
    name = "octobot"
  }
}

resource "argocd_application" "octobot" {
  metadata {
    name = "octobot"
  }

  spec {
    project = "default"
    destination {
      server    = "https://kubernetes.default.svc"
      namespace = kubernetes_namespace_v1.octobot.metadata[0].name
    }

    source {
      repo_url = "https://github.com/rstuhlmuller/octobot-deploy"
      helm {
        values = yamlencode({
          ingress = {
            enabled = true
            hosts = [
              {
                host = "octobot.stinkyboi.com"
                paths = [{
                  path     = "/"
                  pathType = "ImplementationSpecific"
                }]
              }
            ]
            tls = [
              {
                secretName = kubernetes_manifest.octobot_tls.manifest.metadata.name
                hosts      = ["octobot.stinkyboi.com"]
              }
            ]
          }
        })
      }
    }
    sync_policy {
      automated {
        prune     = true
        self_heal = true
      }
    }
  }
}

resource "kubernetes_manifest" "octobot_tls" {
  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "Certificate"
    metadata = {
      name      = "octobot-tls"
      namespace = kubernetes_namespace_v1.octobot.metadata[0].name
    }
    spec = {
      secretName = "octobot-tls"
      issuerRef = {
        name = "cloudflare-clusterissuer"
        kind = "ClusterIssuer"
      }
      dnsNames = [
        "octobot.stinkyboi.com"
      ]
    }
  }
}
