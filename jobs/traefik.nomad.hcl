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

      port "https" {
        static = 443
        to     = 443
      }

      port "admin" {
        static = 8080
        to     = 8080
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
        data = <<EOF
[entryPoints]
  [entryPoints.http]
  address = ":80"
    [entryPoints.http.http.redirections.entryPoint]
    to = "https"
    scheme = "https"

  [entryPoints.https]
  address = ":443"

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

[log]
  level = "INFO"

[accessLog]
  format = "json"

[metrics]
  [metrics.prometheus]
    addEntryPointsLabels = true
    addRoutersLabels = true
    addServicesLabels = true
EOF

        destination = "local/traefik.toml"
      }

      resources {
        cpu    = 200
        memory = 256
      }
    }
  }
}
