job "policy-bot" {
  datacenters = ["homelab"]
  type        = "service"

  group "policy-bot" {
    count = 1

    network {
      mode = "bridge"

      port "http" {
        to = 8080
      }
    }

    service {
      name = "policy-bot"
      port = "http"

      tags = [
        "traefik.enable=true",
        "traefik.http.routers.policy-bot.rule=Host(`policy-bot.stinkyboi.com`)",
        "traefik.http.routers.policy-bot.entrypoints=websecure",
        "traefik.http.routers.policy-bot.tls=true",
        "traefik.http.routers.policy-bot.tls.certresolver=letsencrypt",
      ]

      check {
        name     = "policy-bot-health"
        type     = "http"
        path     = "/api/health"
        port     = "http"
        interval = "30s"
        timeout  = "10s"
      }
    }

    task "policy-bot" {
      driver = "docker"

      config {
        image = "palantirtechnologies/policy-bot:1.41.1"
        ports = ["http"]
        args  = ["server", "--config", "${NOMAD_SECRETS_DIR}/policy-bot.yml"]
      }

      template {
        data        = <<-EOT
          {{ with nomadVar "nomad/jobs/policy-bot/config" }}
          server:
            address: "0.0.0.0"
            port: 8080
            public_url: {{ .public_url | toJSON }}
          logging:
            text: false
            level: "info"
          github:
            web_url: "https://github.com"
            v3_api_url: "https://api.github.com"
            v4_api_url: "https://api.github.com/graphql"
            app:
              integration_id: {{ .github_app_integration_id }}
              webhook_secret: {{ .github_app_webhook_secret | toJSON }}
              private_key: {{ .github_app_private_key | toJSON }}
            oauth:
              client_id: {{ .github_oauth_client_id | toJSON }}
              client_secret: {{ .github_oauth_client_secret | toJSON }}
          sessions:
            key: {{ .sessions_key | toJSON }}
          {{ end }}
        EOT
        destination = "secrets/policy-bot.yml"
        change_mode = "restart"
        perms       = "0400"
      }

      resources {
        cpu    = 500
        memory = 512
      }
    }
  }
}
