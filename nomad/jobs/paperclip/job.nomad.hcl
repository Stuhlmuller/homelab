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
      }
    }

    task "paperclip" {
      driver = "docker"

      config {
        image = "ghcr.io/paperclipai/paperclip:latest"
        ports = ["http"]

        volumes = [
          "local/paperclip-config:/paperclip-config",
        ]
      }

      template {
        data        = <<-EOT
          {{ with nomadVar "nomad/jobs/paperclip/config" }}
          BETTER_AUTH_SECRET="{{ .better_auth_secret }}"
          OPENROUTER_API_KEY="{{ .openrouter_api_key | trimSpace }}"
          PAPERCLIP_DEPLOYMENT_MODE="{{ .deployment_mode }}"
          PAPERCLIP_DEPLOYMENT_EXPOSURE="{{ .deployment_exposure }}"
          PAPERCLIP_PUBLIC_URL="{{ .public_url }}"
          {{ end }}
        EOT
        destination = "local/paperclip-config/.env"
        change_mode = "restart"
        uid         = 1000
        gid         = 1000
        perms       = "0400"
      }

      env {
        PAPERCLIP_CONFIG = "/paperclip-config/config.json"
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
