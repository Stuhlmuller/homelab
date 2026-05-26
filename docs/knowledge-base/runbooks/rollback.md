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
4. OctoBot
5. n8n
6. Radarr and Sonarr
7. Prowlarr
8. media-postgres
9. LiteLLM
10. Deluge
11. Kiali
12. Grafana
13. Descheduler
14. Prometheus
15. platform-storage
16. Tailscale
17. Istio
18. cert-manager
19. external-secrets
20. platform-dns

## Persistent Data

Never delete PVCs during rollback unless the operator explicitly chooses data
removal. Snapshot or verify NFS backup coverage before removing persistent app
registration.

For `media-postgres`, take logical dumps before rollback whenever Sonarr,
Radarr, or Prowlarr have written data to PostgreSQL. Preserve the PostgreSQL
PVC unless intentionally rebuilding from backups.

Policy Bot is stateless. Roll back its public exposure by removing
`policy-bot-hook-funnel` first.

Kiali is stateless. Remove the Kiali CR before removing the operator chart so
the operator can clean up its managed server resources.

## Break-Glass

Live rollback mutation is break-glass only. Any live action must be backfilled
into the repository before the incident is closed.
