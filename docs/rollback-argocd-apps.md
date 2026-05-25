# Argo CD App Rollback

Rollback dependent services before shared foundations. For Terragrunt-driven
registration rollback, remove or disable the downstream Application first, run
`terragrunt run --all plan -no-color`, then apply only after persistent data
handling is clear.

## Order

1. argocd-image-updater
2. OpenClaw
3. Tines
4. Radarr and Sonarr
5. Prowlarr
6. LiteLLM
7. Deluge
8. Grafana
9. Descheduler
10. Prometheus
11. platform-storage
12. Tailscale
13. Istio
14. cert-manager
15. external-secrets

## Persistent Data

Never delete PVCs as part of rollback unless the operator explicitly chooses
data removal. For persistent apps, snapshot or verify NFS backup coverage before
removing Application registration.

## Break-Glass

Direct live mutation is break-glass only. Any live rollback action must be
backfilled into this repository before the incident is considered closed.
