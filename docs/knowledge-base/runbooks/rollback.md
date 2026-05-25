# Argo CD App Rollback

Tags: #runbooks #rollback #argocd

Source: `docs/rollback-argocd-apps.md`

Rollback dependent services before shared foundations. For Terragrunt-driven
registration rollback, remove or disable downstream Applications first, run
`terragrunt run --all plan -no-color`, and apply only after persistent data
handling is clear.

## Current Order

1. `argocd-image-updater`
2. Policy Bot
3. OpenClaw
4. Hummingbot
5. n8n
6. Radarr and Sonarr
7. Prowlarr
8. media-postgres
9. LiteLLM
10. Deluge
11. Grafana
12. Descheduler
13. Prometheus
14. platform-storage
15. Tailscale
16. Istio
17. cert-manager
18. external-secrets
19. platform-dns

## Persistent Data

Never delete PVCs during rollback unless the operator explicitly chooses data
removal. Snapshot or verify NFS backup coverage before removing persistent app
registration.

For `media-postgres`, take logical dumps before rollback whenever Sonarr,
Radarr, or Prowlarr have written data to PostgreSQL. Preserve the PostgreSQL
PVC unless intentionally rebuilding from backups.

Policy Bot is stateless. Roll back its public exposure by removing
`policy-bot-hook-funnel` first.

## Break-Glass

Live rollback mutation is break-glass only. Any live action must be backfilled
into the repository before the incident is closed.
