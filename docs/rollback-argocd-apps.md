# Argo CD App Rollback

Rollback dependent services before shared foundations. For Terragrunt-driven
registration rollback, remove or disable the downstream Application first, run
`terragrunt run --all plan -no-color`, then apply only after persistent data
handling is clear.

## Order

1. argocd-image-updater
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

Never delete PVCs as part of rollback unless the operator explicitly chooses
data removal. For persistent apps, snapshot or verify NFS backup coverage before
removing Application registration.

For `media-postgres`, take PostgreSQL logical dumps before rollback whenever
Sonarr, Radarr, or Prowlarr have already written data to PostgreSQL. Preserve
the PostgreSQL PVC unless intentionally rebuilding the media apps from backups.

For `n8n-postgres`, take a PostgreSQL logical dump before rollback whenever n8n
has already written workflows, users, credentials metadata, or execution
history to PostgreSQL. Preserve both the PostgreSQL PVC and the n8n
`/home/node/.n8n` PVC unless intentionally rebuilding from exports.

Policy Bot is stateless. Roll back its public exposure by removing the
`policy-bot-hook-funnel` Ingress first, then roll back the Deployment and
ExternalSecret if the GitHub App should stop evaluating pull requests.

Kiali is stateless. Remove the Kiali custom resource before removing the
operator chart so the operator can clean up its managed server resources.

## Break-Glass

Direct live mutation is break-glass only. Any live rollback action must be
backfilled into this repository before the incident is considered closed.
