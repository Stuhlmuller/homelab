variable "hivemind_nomad_node_name" {
  type    = string
  default = "nomad-primary"
}

variable "hivemind_source_ref" {
  type = string
  # renovate: datasource=git-refs depName=Stuhlmuller/hivemind packageName=https://github.com/Stuhlmuller/hivemind currentValue=main
  default = "055b3bb7f118af488f1d2b4b6ad3412d29b206ae"
}

job "hivemind" {
  datacenters = ["homelab"]
  type        = "service"

  group "hivemind" {
    count = 1

    update {
      max_parallel      = 1
      min_healthy_time  = "10s"
      healthy_deadline  = "10m"
      progress_deadline = "15m"
    }

    constraint {
      attribute = "${node.unique.name}"
      value     = var.hivemind_nomad_node_name
    }

    network {
      mode = "bridge"

      port "http" {
        to = 8000
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
      name = "hivemind"
      port = "http"

      tags = [
        "traefik.enable=true",
        "traefik.http.routers.hivemind.rule=Host(`hivemind.stinkyboi.com`)",
        "traefik.http.routers.hivemind.entrypoints=websecure",
        "traefik.http.routers.hivemind.tls=true",
        "traefik.http.routers.hivemind.tls.certresolver=letsencrypt",
      ]

      check {
        name     = "hivemind-health"
        type     = "http"
        path     = "/health"
        port     = "http"
        interval = "30s"
        timeout  = "10s"

        header {
          Host = ["hivemind.stinkyboi.com"]
        }
      }
    }

    task "hivemind" {
      driver = "docker"

      config {
        image      = "python:3.12-slim"
        force_pull = true
        ports      = ["http"]
        command    = "sh"
        args = [
          "-ec",
          "python -m pip install --no-cache-dir --upgrade https://github.com/Stuhlmuller/hivemind/archive/${var.hivemind_source_ref}.zip && exec uvicorn hivemind.api:create_app --factory --host 0.0.0.0 --port 8000",
        ]
      }

      env {
        HIVEMIND_DB_PATH    = "/data/hivemind/hivemind.db"
        HIVEMIND_SCHEDULER  = "true"
        HIVEMIND_SOURCE_REF = var.hivemind_source_ref
      }

      volume_mount {
        volume      = "shared-data"
        destination = "/data"
        read_only   = false
      }

      resources {
        cpu    = 500
        memory = 512
      }
    }
  }
}
