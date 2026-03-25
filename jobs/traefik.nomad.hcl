job "traefik" {
  datacenters = ["homelab"]
  type        = "system"

  group "traefik" {
    count = 1

    network {
      port "http" {
        static = 80
        to     = 80
      }

      port "websecure" {
        static = 443
        to     = 443
      }

      port "admin" {
        static = 8080
        to     = 8080
      }
    }

    volume "shared-data" {
      type            = "csi"
      source          = "shared-data"
      read_only       = false
      attachment_mode = "file-system"
      access_mode     = "multi-node-multi-writer"

      mount_options {
        fs_type     = "nfs"
        mount_flags = ["vers=4.1", "noatime", "nodiratime"]
      }
    }

    service {
      name = "traefik"
      port = "http"

      check {
        name     = "alive"
        type     = "tcp"
        port     = "http"
        interval = "10s"
        timeout  = "2s"
      }
    }

    service {
      name = "traefik-admin"
      port = "admin"

      check {
        name     = "admin-alive"
        type     = "http"
        path     = "/ping"
        port     = "admin"
        interval = "10s"
        timeout  = "2s"
      }
    }

    task "traefik" {
      driver = "docker"

      config {
        image        = "traefik:v3.3"
        network_mode = "host"

        volumes = [
          "local/traefik.toml:/etc/traefik/traefik.toml",
        ]

        args = [
          "--configFile=/etc/traefik/traefik.toml",
        ]
      }

      template {
        data        = <<-EOT
          {{ with nomadVar "nomad/jobs/traefik/cf_dns_api_token" }}
          CF_DNS_API_TOKEN={{ .cf_dns_api_token }}
          {{ end }}
        EOT
        destination = "secrets/traefik.env"
        env         = true
      }

      template {
        data = <<EOF
[entryPoints]
  [entryPoints.http]
  address = ":80"
    [entryPoints.http.http.redirections.entryPoint]
    to     = "websecure"
    scheme = "https"

  [entryPoints.websecure]
  address = ":443"
    [entryPoints.websecure.http.tls]
    certResolver = "letsencrypt"

  [entryPoints.traefik]
  address = ":8080"

[api]
  dashboard = true
  insecure  = true

[ping]
  entryPoint = "traefik"

[providers.consulCatalog]
  prefix           = "traefik"
  exposedByDefault = false

  [providers.consulCatalog.endpoint]
    address = "127.0.0.1:8500"
    scheme  = "http"

[certificatesResolvers.letsencrypt.acme]
  email   = "rodman@stuhlmuller.net"
  storage = "/data/traefik/acme.json"

  [certificatesResolvers.letsencrypt.acme.dnsChallenge]
    provider         = "cloudflare"
    delayBeforeCheck = 0
    resolvers        = ["1.1.1.1:53", "8.8.8.8:53"]

[log]
  level = "INFO"

[accessLog]
  format = "json"

[metrics]
  [metrics.prometheus]
    addEntryPointsLabels = true
    addRoutersLabels     = true
    addServicesLabels    = true
EOF

        destination = "local/traefik.toml"
      }

      volume_mount {
        volume      = "shared-data"
        destination = "/data"
      }

      resources {
        cpu    = 200
        memory = 256
      }
    }
  }
}
