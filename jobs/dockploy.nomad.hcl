job "dockploy" {
  datacenters = ["homelab"]
  type        = "service"

  group "dockploy" {
    count = 1

    network {
      port "http" {
        static = 3000
        to     = 3000
      }
    }

    volume "dockploy-data" {
      type            = "csi"
      source          = "shared-data"
      read_only       = false
      access_mode     = "multi-node-multi-writer"
      attachment_mode = "file-system"
    }

    service {
      name = "dockploy"
      port = "http"

      tags = [
        "traefik.enable=true",
        "traefik.http.routers.dockploy.rule=Host(`dockploy.homelab.local`)",
        "traefik.http.routers.dockploy.entrypoints=https",
      ]

      check {
        name     = "dockploy-health"
        type     = "tcp"
        port     = "http"
        interval = "10s"
        timeout  = "2s"
      }
    }

    task "dockploy" {
      driver = "docker"

      volume_mount {
        volume      = "dockploy-data"
        destination = "/data"
        read_only   = false
      }

      config {
        image = "dokploy/dokploy:latest"
        ports = ["http"]

        volumes = [
          "/var/run/docker.sock:/var/run/docker.sock",
        ]
      }

      env {
        # Add any required environment variables here
      }

      resources {
        cpu    = 500
        memory = 512
      }
    }
  }
}
