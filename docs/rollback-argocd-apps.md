# Argo CD App Rollback

Rollback dependent services before shared foundations. For Terragrunt-driven
registration rollback, remove or disable the downstream Application first, run
`terragrunt run --all plan -no-color`, then apply only after persistent data
handling is clear.

## Order

1. argocd-image-updater
2. AFFiNE
3. Policy Bot
4. OpenClaw
5. OctoBot
6. n8n
7. n8n-postgres
8. Radarr and Sonarr
9. Prowlarr
10. media-postgres
11. LiteLLM
12. Deluge
13. Kiali
14. Grafana
15. Descheduler
16. Prometheus
17. platform-storage
18. Tailscale
19. Istio
20. cert-manager
21. external-secrets
22. platform-dns

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

For AFFiNE, take a PostgreSQL logical dump and coordinated NFS backup before
rollback. Preserve the PostgreSQL, Redis, blob-storage, and config claims, and
do not rotate `/homelab/affine/private-key`; changing that ECDSA key invalidates
sessions and can make encrypted application data unreadable.

n8n public webhook exposure is independent of its stored workflow data. Remove
`n8n-webhook-octelium`, its `octelium-public` tunnel/DNS hostname, and the
public `WEBHOOK_URL` first, then roll back the app while preserving both n8n
PVCs unless intentionally rebuilding from exports.

Policy Bot is stateless. Roll back its public exposure by removing the
`policy-bot-webhook-octelium` route and its `octelium-public` tunnel/DNS
hostname first, then roll back the Deployment and ExternalSecret if the GitHub
App should stop evaluating pull requests.

Kiali is stateless. Remove the Kiali custom resource before removing the
operator chart so the operator can clean up its managed server resources.

## Break-Glass

Direct live mutation is break-glass only. Any live rollback action must be
backfilled into this repository before the incident is considered closed.
