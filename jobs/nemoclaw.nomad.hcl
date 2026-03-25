job "nemoclaw" {
  datacenters = ["homelab"]
  type        = "service"

  group "nemoclaw" {
    count = 1

    network {
      mode = "bridge"

      port "gateway" {
        static = 18789
        to     = 18789
      }
    }

    volume "nemoclaw_config" {
      type            = "csi"
      source          = "shared-data"
      read_only       = false
      attachment_mode = "file-system"
      access_mode     = "single-node-writer"

      mount_options {
        fs_type     = "nfs"
        mount_flags = ["vers=4.1", "noatime", "nodiratime"]
      }
    }

    service {
      name = "nemoclaw"
      port = "gateway"

      tags = [
        "traefik.enable=true",
        "traefik.http.routers.nemoclaw.rule=Host(`nemoclaw.stinkyboi.com`)",
        "traefik.http.routers.nemoclaw.entrypoints=websecure",
        "traefik.http.routers.nemoclaw.tls=true",
        "traefik.http.routers.nemoclaw.tls.certresolver=letsencrypt",
        "traefik.http.services.nemoclaw.loadbalancer.server.port=18789",
      ]

      check {
        name     = "nemoclaw-health"
        type     = "http"
        path     = "/"
        port     = "gateway"
        interval = "30s"
        timeout  = "10s"
      }
    }

    task "nemoclaw" {
      driver = "docker"

      config {
        image        = "ghcr.io/nvidia/nemoclaw:latest"
        ports        = ["gateway"]
        network_mode = "bridge"
      }

      env {
        NVIDIA_API_KEY = "${nvidia_api_key}"
        CHAT_UI_URL    = "https://nemoclaw.stinkyboi.com"
      }

      volume_mount {
        volume      = "nemoclaw_config"
        destination = "/sandbox/.nemoclaw"
        read_only   = false
      }

      resources {
        cpu    = 4000
        memory = 8192
      }

      constraint {
        attribute = "${node.class}"
        operator  = "regexp"
        value     = "gpu"
      }
    }
  }
}
