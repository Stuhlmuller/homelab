# Argo CD App Rollback

Rollback dependent services before shared foundations. For Terragrunt-driven
registration rollback, remove or disable the downstream Application first, run
`terragrunt run --all plan -no-color`, then apply only after persistent data
handling is clear.

## Order

1. argocd-image-updater
2. OpenClaw
3. n8n
4. Radarr and Sonarr
5. Prowlarr
6. media-postgres
7. LiteLLM
8. Deluge
9. Grafana
10. Descheduler
11. Prometheus
12. platform-storage
13. Tailscale
14. Istio
15. cert-manager
16. external-secrets

## Persistent Data

Never delete PVCs as part of rollback unless the operator explicitly chooses
data removal. For persistent apps, snapshot or verify NFS backup coverage before
removing Application registration.

For `media-postgres`, take PostgreSQL logical dumps before rollback whenever
Sonarr, Radarr, or Prowlarr have already written data to PostgreSQL. Preserve
the PostgreSQL PVC unless intentionally rebuilding the media apps from backups.

## Break-Glass

Direct live mutation is break-glass only. Any live rollback action must be
backfilled into this repository before the incident is considered closed.
