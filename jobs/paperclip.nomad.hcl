job "paperclip" {
  datacenters = ["homelab"]
  type        = "service"

  group "paperclip" {
    count = 1

    network {
      mode = "bridge"

      port "http" {
        to = 3100
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
      name = "paperclip"
      port = "http"

      tags = [
        "traefik.enable=true",
        "traefik.http.routers.paperclip.rule=Host(`paperclip.stinkyboi.com`)",
        "traefik.http.routers.paperclip.entrypoints=websecure",
        "traefik.http.routers.paperclip.tls=true",
        "traefik.http.routers.paperclip.tls.certresolver=letsencrypt",
      ]

      check {
        name     = "paperclip-health"
        type     = "http"
        path     = "/api/health"
        port     = "http"
        interval = "30s"
        timeout  = "10s"

        header {
          Host = ["paperclip.stinkyboi.com"]
        }
      }
    }

    task "postgres-db" {
      driver = "docker"
      user   = "65534"

      config {
        image = "postgres:17-alpine"
      }

      template {
        data        = <<-EOT
          {{ with nomadVar "nomad/jobs/paperclip/config" }}
          {{ .postgres_password }}
          {{ end }}
        EOT
        destination = "secrets/postgres_password"
        change_mode = "restart"
        uid         = 65534
        gid         = 65534
        perms       = "0400"
      }

      env {
        POSTGRES_DB            = "paperclip"
        POSTGRES_PASSWORD_FILE = "${NOMAD_SECRETS_DIR}/postgres_password"
        POSTGRES_USER          = "paperclip"
        PGDATA                 = "/var/lib/postgresql/data/paperclip-pgdata"
      }

      volume_mount {
        volume      = "shared-data"
        destination = "/var/lib/postgresql/data"
        read_only   = false
      }

      resources {
        cpu    = 500
        memory = 512
      }
    }

    task "paperclip" {
      driver = "docker"

      config {
        image = "ghcr.io/paperclipai/paperclip:latest"
        ports = ["http"]
      }

      template {
        data        = <<-EOT
          {{ with nomadVar "nomad/jobs/paperclip/config" }}
          BETTER_AUTH_SECRET="{{ .better_auth_secret }}"
          PAPERCLIP_AGENT_JWT_SECRET="{{ .better_auth_secret }}"
          DATABASE_URL="postgres://paperclip:{{ .postgres_password }}@127.0.0.1:5432/paperclip"
          PAPERCLIP_DEPLOYMENT_MODE="{{ .deployment_mode }}"
          PAPERCLIP_DEPLOYMENT_EXPOSURE="{{ .deployment_exposure }}"
          PAPERCLIP_PUBLIC_URL="{{ .public_url }}"
          {{ end }}
        EOT
        destination = "secrets/paperclip-runtime.env"
        change_mode = "restart"
        env         = true
      }

      env {
        # Load the persisted instance config so the server also sees the
        # bootstrap-generated .env beside it.
        PAPERCLIP_CONFIG = "/paperclip/instances/default/config.json"
        PAPERCLIP_HOME   = "/paperclip"
      }

      volume_mount {
        volume      = "shared-data"
        destination = "/paperclip"
        read_only   = false
      }

      resources {
        cpu    = 1000
        memory = 1024
      }
    }
  }
}
