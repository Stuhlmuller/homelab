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
5. AFFiNE
6. affine-redis
7. affine-postgres
8. n8n
9. n8n-postgres
10. Radarr and Sonarr
11. Prowlarr
12. media-postgres
13. LiteLLM
14. Deluge
15. Kiali
16. Grafana
17. Descheduler
18. Prometheus
19. platform-storage
20. Tailscale
21. Istio
22. cert-manager
23. external-secrets
24. platform-dns

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

n8n public webhook exposure is independent of its stored workflow data. Remove
`n8n-webhook-funnel`, the `n8n-webhook-funnel` Gateway, and the public
`WEBHOOK_URL` first, then roll back the app while preserving both n8n PVCs
unless intentionally rebuilding from exports.

AFFiNE public exposure is the full web UI. Remove `affine-funnel`, the
`affine-funnel` Gateway, and the public `AFFINE_SERVER_EXTERNAL_URL` first if
external access needs to stop. Take a PostgreSQL logical dump before rollback
whenever AFFiNE has users, workspaces, or documents, and preserve both the
AFFiNE storage PVC and affine-postgres PVC unless intentionally rebuilding from
exports.

Policy Bot is stateless. Roll back its public exposure by removing the
`policy-bot-hook-funnel` Ingress first, then roll back the Deployment and
ExternalSecret if the GitHub App should stop evaluating pull requests.

Kiali is stateless. Remove the Kiali custom resource before removing the
operator chart so the operator can clean up its managed server resources.

## Break-Glass

Direct live mutation is break-glass only. Any live rollback action must be
backfilled into this repository before the incident is considered closed.
