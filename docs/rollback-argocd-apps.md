# Argo CD App Rollback

Rollback dependent services before shared foundations. For Terragrunt-driven
registration rollback, remove or disable the downstream Application first, run
`terragrunt run --all plan -no-color`, then apply only after persistent data
handling is clear.

## Order

1. OpenClaw
2. Tines
3. Radarr and Sonarr
4. LiteLLM
5. Deluge
6. Grafana
7. Descheduler
8. Prometheus
9. platform-storage
10. Tailscale
11. Istio
12. cert-manager
13. external-secrets

## Persistent Data

Never delete PVCs as part of rollback unless the operator explicitly chooses
data removal. For persistent apps, snapshot or verify NFS backup coverage before
removing Application registration.

## Break-Glass

Direct live mutation is break-glass only. Any live rollback action must be
backfilled into this repository before the incident is considered closed.
