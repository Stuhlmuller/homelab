# Workload Inventory

Tags: #workloads #argocd #inventory

This inventory summarizes the current application and platform ownership map.
Treat `docs/argocd-app-onboarding.md`, the `clusters/` tree, and Terragrunt
units as the source of truth when they disagree with this note.

## Import Note

This note reflects the current working tree at import time. Several app changes
are in flight: Policy Bot and Hummingbot desired-state paths exist, while the
Freqtrade desired-state files are deleted in the working tree. Recheck
`clusters/homelab/apps`, `IaC/live/argocd-apps`, and
`docs/argocd-app-onboarding.md` before applying or publishing the branch.

## Platform And Support Applications

| App | Kind | Namespace | GitOps path | Terragrunt path | Depends on |
| --- | --- | --- | --- | --- | --- |
| `platform-dns` | support | `kube-system` | `clusters/homelab/platform/dns` | `IaC/live/argocd-apps/platform-dns` | Argo CD bootstrap |
| `platform-storage` | support | cluster-scoped | `clusters/homelab/platform/storage` | `IaC/live/argocd-apps/platform-storage` | QNAP NFS export |
| `media-postgres` | support | `media` | `clusters/homelab/apps/media-postgres` | `IaC/live/argocd-apps/media-postgres` | external-secrets, platform-storage |

## Requested Applications

| App | Namespace | GitOps path | Terragrunt path | State | Depends on |
| --- | --- | --- | --- | --- | --- |
| `argocd-image-updater` | `argocd` | `clusters/homelab/apps/argocd-image-updater` | `IaC/live/argocd-apps/argocd-image-updater` | controller state only | Argo CD bootstrap |
| `external-secrets` | `external-secrets` | `clusters/homelab/apps/external-secrets` | `IaC/live/argocd-apps/external-secrets` | controller state only | platform-dns |
| `cert-manager` | `cert-manager` | `clusters/homelab/apps/cert-manager` | `IaC/live/argocd-apps/cert-manager` | controller-managed certificates | external-secrets |
| `istio` | `istio-system` | `clusters/homelab/apps/istio` | `IaC/live/argocd-apps/istio` | controller state only | cert-manager |
| `tailscale` | `tailscale` | `clusters/homelab/apps/tailscale` | `IaC/live/argocd-apps/tailscale` | controller state only | external-secrets, istio |
| `prometheus` | `monitoring` | `clusters/homelab/apps/prometheus` | `IaC/live/argocd-apps/prometheus` | persistent metrics and Argo CD scrape config | external-secrets, platform-storage |
| `grafana` | `monitoring` | `clusters/homelab/apps/grafana` | `IaC/live/argocd-apps/grafana` | persistent config, dashboards, alert rules, and Discord alerting webhook secret | external-secrets, cert-manager, istio, tailscale, prometheus, platform-storage |
| `descheduler` | `kube-system` | `clusters/homelab/apps/descheduler` | `IaC/live/argocd-apps/descheduler` | controller state only | prometheus |
| `deluge` | `media` | `clusters/homelab/apps/deluge` | `IaC/live/argocd-apps/deluge` | persistent config and downloads | cert-manager, istio, tailscale, platform-storage |
| `prowlarr` | `media` | `clusters/homelab/apps/prowlarr` | `IaC/live/argocd-apps/prowlarr` | persistent config and PostgreSQL databases | cert-manager, istio, media-postgres, tailscale, platform-storage |
| `radarr` | `media` | `clusters/homelab/apps/radarr` | `IaC/live/argocd-apps/radarr` | persistent config, media refs, and PostgreSQL databases | cert-manager, istio, tailscale, deluge, media-postgres, prowlarr, platform-storage |
| `sonarr` | `media` | `clusters/homelab/apps/sonarr` | `IaC/live/argocd-apps/sonarr` | persistent config, media refs, and PostgreSQL databases | cert-manager, istio, tailscale, deluge, media-postgres, prowlarr, platform-storage |
| `litellm` | `ai` | `clusters/homelab/apps/litellm` | `IaC/live/argocd-apps/litellm` | optional persistent config or DB state | external-secrets, cert-manager, istio, tailscale, platform-storage |
| `openclaw` | `ai` | `clusters/homelab/apps/openclaw` | `IaC/live/argocd-apps/openclaw` | persistent runtime state | external-secrets, cert-manager, istio, tailscale, litellm, platform-storage |
| `n8n` | `automation` | `clusters/homelab/apps/n8n` | `IaC/live/argocd-apps/n8n` | persistent workflows and credential metadata | external-secrets, cert-manager, istio, tailscale, platform-storage |
| `policy-bot` | `automation` | `clusters/homelab/apps/policy-bot` | `IaC/live/argocd-apps/policy-bot` | stateless; credentials from SSM | external-secrets, cert-manager, istio, tailscale |
| `hummingbot` | `finance` | `clusters/homelab/apps/hummingbot` | `IaC/live/argocd-apps/hummingbot` | persistent CLI bot config, logs, scripts, controllers, and encrypted connector state | external-secrets, platform-storage |

## Mesh Policy Summary

Istio ambient is committed for the `ai`, `automation`, and `monitoring`
namespaces. The source of truth is `docs/runtime-isolation.md` plus the
`authorizationpolicy.yaml` files in the affected app overlays.

- `ai` uses a namespace default-deny policy and explicit inbound allows for the
  tailnet gateway to `litellm` and `openclaw`, plus `openclaw` to `litellm`.
- `automation` currently restricts `n8n` inbound access to the tailnet gateway.
  The namespace is not default-denied yet because Policy Bot Funnel traffic
  still needs source-identity validation after rollout.
- `monitoring` restricts Grafana, Prometheus, Alertmanager, and
  kube-state-metrics by service account. The Prometheus operator remains
  unselected until its webhook/control-plane paths are modeled.
- `media` stays out of ambient while Deluge Gluetun/WireGuard and the media app
  ingress model need a repo-owned waypoint or equivalent policy design.

## In-Flight Or Historical Rows

- `freqtrade` appears in older onboarding material, but its app and Terragrunt
  files are deleted in the current working tree. Treat it as removed or
  superseded by Hummingbot only after the owning PR reconciles the source docs.

## Update Checklist

When a workload changes, update this note for:

- Namespace or path moves.
- New or removed dependencies.
- New ingress host or exposure type.
- New ExternalSecret or SSM parameter contract.
- Persistent storage, backup, restore, or rollback behavior changes.
