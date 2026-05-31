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
6. n8n-postgres
7. Radarr and Sonarr
8. Prowlarr
9. media-postgres
10. LiteLLM
11. Deluge
12. Kiali
13. Grafana
14. Descheduler
15. Prometheus
16. platform-storage
17. Tailscale
18. Istio
19. cert-manager
20. external-secrets
21. platform-dns

## Persistent Data

Never delete PVCs during rollback unless the operator explicitly chooses data
removal. Snapshot or verify NFS backup coverage before removing persistent app
registration.

For `media-postgres`, take logical dumps before rollback whenever Sonarr,
Radarr, or Prowlarr have written data to PostgreSQL. Preserve the PostgreSQL
PVC unless intentionally rebuilding from backups.

For `n8n-postgres`, take a logical dump before rollback whenever n8n has
written workflows, users, credentials metadata, or execution history to
PostgreSQL. Preserve both the PostgreSQL PVC and n8n PVC unless intentionally
rebuilding from exports.

n8n public webhook exposure is independent of stored workflow data. Remove
`n8n-webhook-funnel`, its Gateway, and the public `WEBHOOK_URL` before rolling
back the app.

Policy Bot is stateless. Roll back its public exposure by removing
`policy-bot-hook-funnel` first.

Kiali is stateless. Remove the Kiali CR before removing the operator chart so
the operator can clean up its managed server resources.

## Break-Glass

Live rollback mutation is break-glass only. Any live action must be backfilled
into the repository before the incident is closed.
