variable "openclaw_nomad_node_name" {
  type    = string
  default = "nomad-primary"
}

job "openclaw" {
  datacenters = ["homelab"]
  type        = "service"

  group "openclaw" {
    count = 1

    constraint {
      attribute = "${node.unique.name}"
      value     = var.openclaw_nomad_node_name
    }

    network {
      mode = "bridge"

      port "http" {
        to = 18789
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
      name = "openclaw"
      port = "http"

      tags = [
        "traefik.enable=true",
        "traefik.http.routers.openclaw.rule=Host(`openclaw.stinkyboi.com`)",
        "traefik.http.routers.openclaw.entrypoints=websecure",
        "traefik.http.routers.openclaw.tls=true",
        "traefik.http.routers.openclaw.tls.certresolver=letsencrypt",
      ]

      check {
        name     = "openclaw-ready"
        type     = "http"
        path     = "/readyz"
        port     = "http"
        interval = "30s"
        timeout  = "10s"
      }
    }

    task "openclaw-init" {
      driver = "docker"
      user   = "1000"
      lifecycle {
        hook = "prestart"
      }

      config {
        image   = "ghcr.io/openclaw/openclaw:2026.4.15"
        command = "sh"
        args = [
          "-c",
          "mkdir -p /data/openclaw/config /data/openclaw/state /data/openclaw/workspace",
        ]
      }

      volume_mount {
        volume      = "shared-data"
        destination = "/data"
        read_only   = false
      }

      resources {
        cpu    = 100
        memory = 128
      }
    }

    task "openclaw" {
      driver = "docker"
      user   = "1000"

      config {
        image   = "ghcr.io/openclaw/openclaw:2026.4.15"
        command = "sh"
        args = [
          "-c",
          "if [ ! -s /data/openclaw/config/openclaw.json ]; then cp ${NOMAD_SECRETS_DIR}/openclaw.bootstrap.json /data/openclaw/config/openclaw.json; fi; chmod 0600 /data/openclaw/config/openclaw.json; exec node dist/index.js gateway --port 18789",
        ]
        ports = ["http"]
      }

      template {
        data        = <<-EOT
          {{- with nomadVar "nomad/jobs/openclaw/config" -}}
          {
            gateway: {
              mode: "local",
              bind: "lan",
              auth: {
                mode: "token",
                token: {{ .gateway_token.Value | toJSON }},
              },
              controlUi: {
                allowedOrigins: [{{ .public_url.Value | toJSON }}],
              },
            },
            agents: {
              defaults: {
                workspace: "/data/openclaw/workspace",
              },
            },
            session: {
              dmScope: "per-channel-peer",
            },
          }
        {{- end -}}
        EOT
        destination = "secrets/openclaw.bootstrap.json"
        change_mode = "restart"
        uid         = 1000
        gid         = 1000
        perms       = "0400"
      }

      env {
        OPENCLAW_CONFIG_PATH = "/data/openclaw/config/openclaw.json"
        OPENCLAW_STATE_DIR   = "/data/openclaw/state"
      }

      volume_mount {
        volume      = "shared-data"
        destination = "/data"
        read_only   = false
      }

      resources {
        cpu    = 3000
        memory = 4096
      }
    }
  }
}
