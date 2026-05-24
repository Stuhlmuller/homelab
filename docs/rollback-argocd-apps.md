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
5. LiteLLM
6. Deluge
7. Grafana
8. Descheduler
9. Prometheus
10. platform-storage
11. Tailscale
12. Istio
13. cert-manager
14. external-secrets

## Persistent Data

Never delete PVCs as part of rollback unless the operator explicitly chooses
data removal. For persistent apps, snapshot or verify NFS backup coverage before
removing Application registration.

## Break-Glass

Direct live mutation is break-glass only. Any live rollback action must be
backfilled into this repository before the incident is considered closed.
