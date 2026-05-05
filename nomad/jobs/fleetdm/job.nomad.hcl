variable "fleetdm_nomad_node_name" {
  type    = string
  default = "nomad-primary"
}

job "fleetdm" {
  datacenters = ["homelab"]
  type        = "service"

  group "fleetdm" {
    count = 1

    update {
      max_parallel      = 1
      min_healthy_time  = "10s"
      healthy_deadline  = "15m"
      progress_deadline = "20m"
    }

    constraint {
      attribute = "${node.unique.name}"
      value     = var.fleetdm_nomad_node_name
    }

    network {
      mode = "bridge"

      port "http" {
        to = 1337
      }
    }

    volume "fleetdm_data" {
      type      = "host"
      source    = "fleetdm_data"
      read_only = false
    }

    service {
      name = "fleetdm"
      port = "http"

      tags = [
        "traefik.enable=true",
        "traefik.http.routers.fleetdm.rule=Host(`fleet.stinkyboi.com`)",
        "traefik.http.routers.fleetdm.entrypoints=websecure",
        "traefik.http.routers.fleetdm.tls=true",
        "traefik.http.routers.fleetdm.tls.certresolver=letsencrypt",
      ]

      check {
        name     = "fleetdm-health"
        type     = "http"
        path     = "/healthz"
        port     = "http"
        interval = "30s"
        timeout  = "10s"

        header {
          Host = ["fleet.stinkyboi.com"]
        }
      }
    }

    task "fleet-init" {
      driver = "docker"

      lifecycle {
        hook    = "prestart"
        sidecar = false
      }

      config {
        image   = "alpine:3.22"
        command = "sh"
        args = [
          "-ec",
          "mkdir -p /srv/fleetdm/mysql /srv/fleetdm/redis /srv/fleetdm/fleet /srv/fleetdm/logs /srv/fleetdm/vulndb && chown -R 100:101 /srv/fleetdm/fleet /srv/fleetdm/logs /srv/fleetdm/vulndb && chown -R 999:999 /srv/fleetdm/redis",
        ]
      }

      volume_mount {
        volume      = "fleetdm_data"
        destination = "/srv/fleetdm"
        read_only   = false
      }

      resources {
        cpu    = 100
        memory = 64
      }
    }

    task "mysql" {
      driver = "docker"

      config {
        image = "mysql:8.4.8"
        args = [
          "--datadir=/srv/fleetdm/mysql",
          "--character-set-server=utf8mb4",
          "--collation-server=utf8mb4_unicode_ci",
        ]
      }

      template {
        data        = <<-EOT
          {{- with nomadVar "nomad/jobs/fleetdm/config" -}}
          {{- .mysql_root_password.Value | trimSpace -}}
          {{- end -}}
        EOT
        destination = "secrets/mysql_root_password"
        change_mode = "restart"
        perms       = "0400"
      }

      template {
        data        = <<-EOT
          {{- with nomadVar "nomad/jobs/fleetdm/config" -}}
          {{- .mysql_password.Value | trimSpace -}}
          {{- end -}}
        EOT
        destination = "secrets/mysql_password"
        change_mode = "restart"
        uid         = 100
        gid         = 101
        perms       = "0400"
      }

      env {
        MYSQL_DATABASE           = "fleet"
        MYSQL_PASSWORD_FILE      = "${NOMAD_SECRETS_DIR}/mysql_password"
        MYSQL_ROOT_PASSWORD_FILE = "${NOMAD_SECRETS_DIR}/mysql_root_password"
        MYSQL_USER               = "fleet"
      }

      volume_mount {
        volume      = "fleetdm_data"
        destination = "/srv/fleetdm"
        read_only   = false
      }

      resources {
        cpu    = 1000
        memory = 1024
      }
    }

    task "redis" {
      driver = "docker"

      config {
        image = "redis:6.2.21-alpine"
        args  = ["redis-server", "--appendonly", "yes", "--dir", "/srv/fleetdm/redis"]
      }

      volume_mount {
        volume      = "fleetdm_data"
        destination = "/srv/fleetdm"
        read_only   = false
      }

      resources {
        cpu    = 250
        memory = 256
      }
    }

    task "fleetdm" {
      driver = "docker"

      config {
        image   = "fleetdm/fleet:v4.84.1"
        ports   = ["http"]
        command = "sh"
        args = [
          "-ec",
          "/usr/bin/fleet prepare db --no-prompt && exec /usr/bin/fleet serve",
        ]
      }

      template {
        data        = <<-EOT
          {{ with nomadVar "nomad/jobs/fleetdm/config" }}
          FLEET_LICENSE_KEY={{ .license_key | toJSON }}
          FLEET_SERVER_PRIVATE_KEY={{ .server_private_key.Value | trimSpace | toJSON }}
          {{ end }}
        EOT
        destination = "secrets/fleet-runtime.env"
        change_mode = "restart"
        env         = true
      }

      template {
        data        = <<-EOT
          {{- with nomadVar "nomad/jobs/fleetdm/config" -}}
          {{- .mysql_password.Value | trimSpace -}}
          {{- end -}}
        EOT
        destination = "secrets/mysql_password"
        change_mode = "restart"
        uid         = 100
        gid         = 101
        perms       = "0400"
      }

      env {
        FLEET_FILESYSTEM_RESULT_LOG_FILE              = "/srv/fleetdm/logs/osqueryd.results.log"
        FLEET_FILESYSTEM_STATUS_LOG_FILE              = "/srv/fleetdm/logs/osqueryd.status.log"
        FLEET_LOGGING_JSON                            = "true"
        FLEET_MYSQL_ADDRESS                           = "127.0.0.1:3306"
        FLEET_MYSQL_DATABASE                          = "fleet"
        FLEET_MYSQL_PASSWORD_PATH                     = "${NOMAD_SECRETS_DIR}/mysql_password"
        FLEET_MYSQL_USERNAME                          = "fleet"
        FLEET_OSQUERY_LABEL_UPDATE_INTERVAL           = "1h"
        FLEET_OSQUERY_STATUS_LOG_PLUGIN               = "filesystem"
        FLEET_REDIS_ADDRESS                           = "127.0.0.1:6379"
        FLEET_SERVER_ADDRESS                          = "0.0.0.0:1337"
        FLEET_SERVER_TLS                              = "false"
        FLEET_SERVER_TRUSTED_PROXIES                  = "header:x-real-ip"
        FLEET_SESSION_DURATION                        = "24h"
        FLEET_VULNERABILITIES_CURRENT_INSTANCE_CHECKS = "yes"
        FLEET_VULNERABILITIES_DATABASES_PATH          = "/srv/fleetdm/vulndb"
        FLEET_VULNERABILITIES_PERIODICITY             = "1h"
      }

      volume_mount {
        volume      = "fleetdm_data"
        destination = "/srv/fleetdm"
        read_only   = false
      }

      resources {
        cpu    = 2000
        memory = 2048
      }
    }
  }
}
