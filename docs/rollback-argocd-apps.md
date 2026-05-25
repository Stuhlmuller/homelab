# Argo CD App Rollback

Rollback dependent services before shared foundations. For Terragrunt-driven
registration rollback, remove or disable the downstream Application first, run
`terragrunt run --all plan -no-color`, then apply only after persistent data
handling is clear.

## Order

1. argocd-image-updater
2. OpenClaw
3. Freqtrade
4. n8n
5. Radarr and Sonarr
6. Prowlarr
7. media-postgres
8. LiteLLM
9. Deluge
10. Grafana
11. Descheduler
12. Prometheus
13. platform-storage
14. Tailscale
15. Istio
16. cert-manager
17. external-secrets
18. platform-dns

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
