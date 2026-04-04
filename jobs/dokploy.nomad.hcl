job "dokploy" {
  datacenters = ["homelab"]
  type        = "service"

  group "dokploy" {
    count = 1

    network {
      mode = "host"

      port "http" {
        static = 3000
      }

      port "postgres" {
        static = 5432
      }

      port "redis" {
        static = 6379
      }
    }

    volume "dokploy_data" {
      type      = "host"
      source    = "dockploy_data"
      read_only = false
    }

    volume "postgres_data" {
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

    volume "redis_data" {
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
        "traefik.http.services.dokploy.loadbalancer.server.port=3000",
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

      # Run as nobody (65534) - the UID that NFS maps all unknown UIDs to,
      # so files created on the NFS share are owned by the same UID postgres runs as
      user = "65534"

      config {
        image        = "postgres:16-alpine"
        network_mode = "host"
      }

      env {
        POSTGRES_DB       = "dokploy"
        POSTGRES_USER     = "dokploy"
        POSTGRES_PASSWORD = "dokploy_secure_password"
        PGDATA            = "/var/lib/postgresql/data/pgdata"
      }

      volume_mount {
        volume      = "postgres_data"
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

      # Run as nobody (65534) - the UID that NFS maps all unknown UIDs to
      user = "65534"

      config {
        image        = "redis:7-alpine"
        network_mode = "host"
        args         = ["redis-server", "--save", "60", "1", "--dir", "/data/redis-data"]
      }

      volume_mount {
        volume      = "redis_data"
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
        image        = "dokploy/dokploy:latest"
        ports        = ["http"]
        network_mode = "host"
      }

      volume_mount {
        volume      = "dokploy_data"
        destination = "/etc/dokploy"
        read_only   = false
      }

      env {
        DOKPLOY_PORT            = "3000"
        DOKPLOY_TRAEFIK_ENABLED = "false"
        DOKPLOY_SERVER_IP       = "10.1.0.200"
        DOKPLOY_ROOT_DOMAIN     = "homelab.local"

        # Point dokploy at the postgres and redis tasks sharing the host network
        DATABASE_URL = "postgresql://dokploy:dokploy_secure_password@127.0.0.1:5432/dokploy" #checkov:skip=CKV_SECRET_4: placeholder
        REDIS_URL    = "redis://127.0.0.1:6379"
      }

      resources {
        cpu    = 1000
        memory = 2048
      }
    }
  }
}
