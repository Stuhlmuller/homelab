job "traefik" {
  datacenters = ["homelab"]
  type        = "service"

  group "traefik" {
    count = 1

    network {
      port "http" {
        static = 8080
      }

      port "websecure" {
        static = 443
        to     = 443
      }

      port "api" {
        static = 8081
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

      check {
        name     = "alive"
        type     = "tcp"
        port     = "http"
        interval = "10s"
        timeout  = "2s"
      }
    }

    task "traefik" {
      driver = "docker"

      config {
        image        = "traefik:v3.6.6"
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
    address = ":8080"
    [entryPoints.traefik]
    address = ":8081"
    [entryPoints.websecure]
    address = ":443"
    [entryPoints.websecure.http.tls]
    certResolver = "letsencrypt"
    [entryPoints.http.http.redirections.entryPoint]
    to     = "websecure"
    scheme = "https"

[api]
    dashboard = true
    insecure  = true

# Enable Consul Catalog configuration backend.
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
EOF

        destination = "local/traefik.toml"
      }

      volume_mount {
        volume      = "shared-data"
        destination = "/data"
      }

      resources {
        cpu    = 100
        memory = 128
      }
    }
  }
}
