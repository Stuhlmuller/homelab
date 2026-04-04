job "dokploy" {
  datacenters = ["homelab"]
  type        = "service"

  group "dokploy" {
    count = 1

    network {
      mode = "bridge"

      port "http" {
        to = 3000
      }
    }

    volume "dokploy_data" {
      type      = "host"
      source    = "dockploy_data"
      read_only = false
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
      name = "dokploy"
      port = "http"

      tags = [
        "traefik.enable=true",
        "traefik.http.routers.dokploy.rule=Host(`dokploy.stinkyboi.com`)",
        "traefik.http.routers.dokploy.entrypoints=websecure",
        "traefik.http.routers.dokploy.tls=true",
        "traefik.http.routers.dokploy.tls.certresolver=letsencrypt",
      ]

      check {
        name     = "dokploy-health"
        type     = "http"
        path     = "/api/health"
        port     = "http"
        interval = "30s"
        timeout  = "10s"
      }
    }

    task "postgres-db" {
      driver = "docker"
      user   = "65534"

      config {
        image = "postgres:16-alpine"
      }

      template {
        data        = <<-EOT
          {{ with nomadVar "nomad/jobs/dokploy/config" }}
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
        POSTGRES_DB            = "dokploy"
        POSTGRES_PASSWORD_FILE = "${NOMAD_SECRETS_DIR}/postgres_password"
        POSTGRES_USER          = "dokploy"
        PGDATA                 = "/var/lib/postgresql/data/pgdata"
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

    task "redis" {
      driver = "docker"
      user   = "65534"

      config {
        image = "redis:7-alpine"
        args  = ["redis-server", "--save", "60", "1", "--dir", "/data/redis-data"]
      }

      volume_mount {
        volume      = "shared-data"
        destination = "/data"
        read_only   = false
      }

      resources {
        cpu    = 200
        memory = 256
      }
    }

    task "dokploy" {
      driver = "docker"

      config {
        image = "dokploy/dokploy:latest"
        ports = ["http"]
      }

      template {
        data        = <<-EOT
          {{ with nomadVar "nomad/jobs/dokploy/config" }}
          DOKPLOY_ROOT_DOMAIN={{ .root_domain }}
          DOKPLOY_SERVER_IP={{ .server_ip }}
          {{ end }}
        EOT
        destination = "local/dokploy.env"
        env         = true
      }

      template {
        data        = <<-EOT
          {{ with nomadVar "nomad/jobs/dokploy/config" }}
          {{ .postgres_password }}
          {{ end }}
        EOT
        destination = "secrets/postgres_password"
        change_mode = "restart"
        perms       = "0400"
      }

      volume_mount {
        volume      = "dokploy_data"
        destination = "/etc/dokploy"
        read_only   = false
      }

      env {
        DOKPLOY_PORT            = "3000"
        DOKPLOY_TRAEFIK_ENABLED = "false"
        POSTGRES_HOST           = "127.0.0.1"
        POSTGRES_PORT           = "5432"
        POSTGRES_PASSWORD_FILE  = "${NOMAD_SECRETS_DIR}/postgres_password"
      }

      resources {
        cpu    = 1000
        memory = 2048
      }
    }
  }
}
