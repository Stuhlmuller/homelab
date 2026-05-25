# Argo CD App Rollback

Rollback dependent services before shared foundations. For Terragrunt-driven
registration rollback, remove or disable the downstream Application first, run
`terragrunt run --all plan -no-color`, then apply only after persistent data
handling is clear.

## Order

1. argocd-image-updater
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

Never delete PVCs as part of rollback unless the operator explicitly chooses
data removal. For persistent apps, snapshot or verify NFS backup coverage before
removing Application registration.

For `media-postgres`, take PostgreSQL logical dumps before rollback whenever
Sonarr, Radarr, or Prowlarr have already written data to PostgreSQL. Preserve
the PostgreSQL PVC unless intentionally rebuilding the media apps from backups.

Policy Bot is stateless. Roll back its public exposure by removing the
`policy-bot-hook-funnel` Ingress first, then roll back the Deployment and
ExternalSecret if the GitHub App should stop evaluating pull requests.

## Break-Glass

Direct live mutation is break-glass only. Any live rollback action must be
backfilled into this repository before the incident is considered closed.
