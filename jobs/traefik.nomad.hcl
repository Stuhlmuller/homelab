job "traefik" {
  datacenters = ["homelab"]
  type        = "service"

  group "traefik" {
    count = 1

    constraint {
      attribute = "${node.unique.name}"
      value     = "nomad-primary"
    }

    network {
      mode = "host"

      port "http" {
        static = 80
      }

      port "websecure" {
        static = 443
      }

      port "admin" {
        static = 8080
      }

      port "funnel" {
        static = 18080
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
      port = "admin"

      tags = [
        "traefik.enable=true",
        "traefik.http.routers.traefik.rule=Host(`traefik.stinkyboi.com`)",
        "traefik.http.routers.traefik.entrypoints=websecure",
        "traefik.http.routers.traefik.tls=true",
        "traefik.http.routers.traefik.tls.certresolver=letsencrypt",
        "traefik.http.routers.traefik.service=api@internal",
      ]

      check {
        name     = "alive"
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
        image        = "traefik:v3.6.6"
        network_mode = "host"

        volumes = [
          "local/traefik.toml:/etc/traefik/traefik.toml",
          "local/dynamic.toml:/etc/traefik/dynamic.toml",
        ]

        args = ["--configFile=/etc/traefik/traefik.toml"]
      }

      template {
        data        = <<-EOT
          {{- with nomadVar "nomad/jobs/traefik/cf_dns_api_token" -}}{{- .cf_dns_api_token -}}{{- end -}}
        EOT
        destination = "secrets/cf_dns_api_token"
        change_mode = "restart"
        perms       = "0400"
      }

      env {
        CF_DNS_API_TOKEN_FILE = "${NOMAD_SECRETS_DIR}/cf_dns_api_token"
      }

      template {
        data        = <<-EOF
[entryPoints]
  [entryPoints.http]
    address = ":80"
    [entryPoints.http.http.redirections.entryPoint]
      to     = "websecure"
      scheme = "https"

  [entryPoints.traefik]
    address = ":8080"

  [entryPoints.websecure]
    address = ":443"
    [entryPoints.websecure.http.tls]
      certResolver = "letsencrypt"

  [entryPoints.funnel]
    address = ":18080"

[api]
  dashboard = true
  insecure  = false

[ping]
  entryPoint = "traefik"

[providers.consulCatalog]
  prefix           = "traefik"
  exposedByDefault = false

  [providers.consulCatalog.endpoint]
    address = "127.0.0.1:8500"
    scheme  = "http"

[providers.file]
  filename = "/etc/traefik/dynamic.toml"
  watch    = true

[log]
  level = "INFO"

[accessLog]

[certificatesResolvers.letsencrypt.acme]
  email   = "rodman@stuhlmuller.net"
  storage = "/data/traefik/acme.json"

  [certificatesResolvers.letsencrypt.acme.dnsChallenge]
    provider         = "cloudflare"
    delayBeforeCheck = 0
    resolvers        = ["1.1.1.1:53", "8.8.8.8:53"]
EOF
        destination = "local/traefik.toml"
        change_mode = "restart"
      }

      template {
        data        = <<-EOF
[http.routers]
  [http.routers.nomad]
    rule        = "Host(`nomad.stinkyboi.com`)"
    entryPoints = ["websecure"]
    service     = "nomad-ui"
    [http.routers.nomad.tls]
      certResolver = "letsencrypt"

  [http.routers.policy-bot-funnel]
    rule        = "Host(`acer.tail67beb.ts.net`) && (PathPrefix(`/auth`) || PathPrefix(`/hook`))"
    entryPoints = ["funnel"]
    service     = "policy-bot@consulcatalog"

  [http.routers.consul]
    rule        = "Host(`consul.stinkyboi.com`)"
    entryPoints = ["websecure"]
    service     = "consul-ui"
    [http.routers.consul.tls]
      certResolver = "letsencrypt"

[http.services]
  [http.services.nomad-ui.loadBalancer]
    passHostHeader = true
    [http.services.nomad-ui.loadBalancer.healthCheck]
      path     = "/v1/status/leader"
      interval = "10s"
      timeout  = "2s"
    [[http.services.nomad-ui.loadBalancer.servers]]
      url = "http://10.1.0.200:4646"
    [[http.services.nomad-ui.loadBalancer.servers]]
      url = "http://10.1.0.201:4646"
    [[http.services.nomad-ui.loadBalancer.servers]]
      url = "http://10.1.0.202:4646"

  [http.services.consul-ui.loadBalancer]
    passHostHeader = true
    [http.services.consul-ui.loadBalancer.healthCheck]
      path     = "/v1/status/leader"
      interval = "10s"
      timeout  = "2s"
    [[http.services.consul-ui.loadBalancer.servers]]
      url = "http://10.1.0.200:8500"
    [[http.services.consul-ui.loadBalancer.servers]]
      url = "http://10.1.0.201:8500"
    [[http.services.consul-ui.loadBalancer.servers]]
      url = "http://10.1.0.202:8500"
EOF
        destination = "local/dynamic.toml"
        change_mode = "restart"
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
