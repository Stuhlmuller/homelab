job "openclaw" {
  datacenters = ["homelab"]
  type        = "service"

  group "openclaw" {
    count = 1

    constraint {
      attribute = "${node.unique.name}"
      value     = "nomad-primary"
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
        args    = ["-c", "mkdir -p /data/openclaw/config /data/openclaw/state /data/openclaw/workspace /data/openclaw/codex-cli /data/openclaw/home; if [ -s /data/openclaw/config/openclaw.json ]; then node -e 'const fs=require(\"fs\"); const p=\"/data/openclaw/config/openclaw.json\"; const cfg=Function(\"return (\"+fs.readFileSync(p,\"utf8\")+\")\")(); const ref=\"codex/gpt-5.4\"; cfg.agents ??= {}; cfg.agents.defaults ??= {}; cfg.agents.defaults.model ??= {}; cfg.agents.defaults.model.primary = ref; if (cfg.agents.defaults.models) { delete cfg.agents.defaults.models[\"openai-codex/gpt-5.4\"]; delete cfg.agents.defaults.models[ref]; if (Object.keys(cfg.agents.defaults.models).length === 0) delete cfg.agents.defaults.models; } cfg.channels ??= {}; cfg.channels.discord ??= {}; cfg.channels.discord.heartbeat ??= {}; cfg.channels.discord.heartbeat.showAlerts = false; fs.writeFileSync(p, JSON.stringify(cfg, null, 2));'; fi; if [ ! -x /data/openclaw/codex-cli/node_modules/.bin/codex ] || [ ! -x /data/openclaw/codex-cli/node_modules/.bin/obsidian ]; then npm install --prefix /data/openclaw/codex-cli @openai/codex@0.130.0 obsidian-cli@0.5.1; fi"]
      }

      volume_mount {
        volume      = "shared-data"
        destination = "/data"
        read_only   = false
      }

      resources {
        cpu    = 100
        memory = 1024
      }
    }

    task "openclaw" {
      driver = "docker"
      user   = "1000"

      config {
        image   = "ghcr.io/openclaw/openclaw:2026.4.15"
        ports   = ["http"]
        command = "sh"
        args    = ["-c", "if [ ! -s /data/openclaw/config/openclaw.json ]; then cp ${NOMAD_SECRETS_DIR}/openclaw.bootstrap.json /data/openclaw/config/openclaw.json; fi; chmod 0600 /data/openclaw/config/openclaw.json; openclaw models status >/tmp/openclaw-models-status.log 2>&1 || true; exec node dist/index.js gateway --port 18789"]
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
                model: {
                  primary: "codex/gpt-5.4",
                },
                workspace: "/data/openclaw/workspace",
              },
            },
            plugins: {
              load: {
                paths: ["/app/dist/extensions/discord"],
              },
            },
            channels: {
              discord: {
                enabled: true,
                dmPolicy: "pairing",
                allowFrom: [],
                activity: "OpenClaw",
                status: "online",
                heartbeat: {
                  showAlerts: false,
                },
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

      template {
        data        = <<-EOT
          {{- with nomadVar "nomad/jobs/openclaw/discord" -}}
          DISCORD_BOT_TOKEN="{{ .bot_token.Value | trimSpace }}"
          {{- end -}}
        EOT
        destination = "secrets/openclaw-runtime.env"
        change_mode = "restart"
        env         = true
      }

      env {
        HOME                   = "/data/openclaw/home"
        OPENCLAW_AGENT_RUNTIME = "codex"
        OPENCLAW_CONFIG_PATH   = "/data/openclaw/config/openclaw.json"
        OPENCLAW_STATE_DIR     = "/data/openclaw/state"
        PATH                   = "/data/openclaw/codex-cli/node_modules/.bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
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
