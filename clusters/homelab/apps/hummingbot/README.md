# Hummingbot Retired State

Hummingbot is no longer the active finance trading bot. OctoBot owns the
current UI at `https://octobot.stinkyboi.com`.

This path intentionally keeps only the old Hummingbot PVCs under Argo CD. The
retired Application gives Argo a valid source path, lets it prune the old
Deployment, Service, ExternalSecret, and VirtualService, and protects the PVCs
from app deletion with Argo sync annotations.

## Retained Data

- `hummingbot-conf`: encrypted client configuration and connector files
- `hummingbot-logs`: historical bot logs
- `hummingbot-data`: runtime data
- `hummingbot-certs`: generated client certificates
- `hummingbot-scripts`: custom scripts
- `hummingbot-controllers`: controller files

The SSM parameter `/homelab/hummingbot/config-password` is retained for
rollback while these PVCs exist. Do not delete it until a separate data-retention
decision removes or archives the PVCs.

## Validation

```sh
kubectl kustomize clusters/homelab/apps/hummingbot
kubectl -n argocd get application hummingbot
kubectl -n finance get pvc -l app.kubernetes.io/instance=hummingbot
```

Expected result: the Hummingbot Application is synced and healthy, no Hummingbot
Deployment or route is running, and the retained PVCs are bound.
