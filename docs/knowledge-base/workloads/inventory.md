# Workload Inventory

Tags: #workloads #argocd #inventory

This inventory summarizes the current application and platform ownership map.
Treat `docs/argocd-app-onboarding.md`, the `clusters/` tree, and Terragrunt
units as the source of truth when they disagree with this note.

## Import Note

This note reflects the current working tree. OctoBot is the finance namespace
trading workload with Octelium-targeted UI access and tailnet fallback until the
Octelium e2e gate passes.

## Platform And Support Applications

| App | Kind | Namespace | GitOps path | Terragrunt path | Depends on |
| --- | --- | --- | --- | --- | --- |
| `platform-dns` | support | `kube-system` | `clusters/homelab/platform/dns` | `IaC/live/argocd-apps/platform-dns` | Argo CD bootstrap |
| `platform-storage` | support | cluster-scoped | `clusters/homelab/platform/storage` | `IaC/live/argocd-apps/platform-storage` | QNAP NFS export |
| `media-postgres` | support | `media` | `clusters/homelab/apps/media-postgres` | `IaC/live/argocd-apps/media-postgres` | external-secrets, platform-storage |
| `n8n-postgres` | support | `automation` | `clusters/homelab/apps/n8n-postgres` | `IaC/live/argocd-apps/n8n-postgres` | external-secrets, platform-storage |

## Requested Applications

| App | Namespace | GitOps path | Terragrunt path | State | Depends on |
| --- | --- | --- | --- | --- | --- |
| `argocd-image-updater` | `argocd` | `clusters/homelab/apps/argocd-image-updater` | `IaC/live/argocd-apps/argocd-image-updater` | controller state and GitHub App PR credential | external-secrets |
| `external-secrets` | `external-secrets` | `clusters/homelab/apps/external-secrets` | `IaC/live/argocd-apps/external-secrets` | controller state only | platform-dns |
| `cert-manager` | `cert-manager` | `clusters/homelab/apps/cert-manager` | `IaC/live/argocd-apps/cert-manager` | controller-managed certificates | external-secrets |
| `istio` | `istio-system` | `clusters/homelab/apps/istio` | `IaC/live/argocd-apps/istio` | controller state only | cert-manager |
| `tailscale` | `tailscale` | `clusters/homelab/apps/tailscale` | `IaC/live/argocd-apps/tailscale` | controller state only | external-secrets, istio |
| `octelium` | `octelium-client` | `clusters/homelab/apps/octelium` | `IaC/live/argocd-apps/octelium` | stateless rootless Octelium client bridge and target human app access plane for Cluster domain `octelium.stinkyboi.com`; serves the explicit homelab WEB Service catalog from `docs/examples/octelium/homelab-services.yaml`, plus Podinfo demo service; auth token is `/homelab/octelium/client-auth-token`; cutover is gated by `scripts/octelium-e2e-check.sh`; Enterprise package `octeliumee` desired version `0.22.0` is installed with `scripts/octelium-enterprise-package.sh` | external-secrets, istio |
| `prometheus` | `monitoring` | `clusters/homelab/apps/prometheus` | `IaC/live/argocd-apps/prometheus` | persistent metrics, Alertmanager state, Argo CD scrape config, and Alertmanager Discord/OpenClaw notification secrets | external-secrets, platform-storage |
| `grafana` | `monitoring` | `clusters/homelab/apps/grafana` | `IaC/live/argocd-apps/grafana` | persistent config, dashboards, platform/workload alert rules, expected hardware-node and Kubernetes-node alerting, public GitHub API PR/status polling, and stale direct receiver cleanup | external-secrets, cert-manager, istio, tailscale, prometheus, platform-storage |
| `kiali` | `monitoring` | `clusters/homelab/apps/kiali` | `IaC/live/argocd-apps/kiali` | controller state only; read-only mesh UI | istio, tailscale, prometheus, grafana |
| `compass` | `monitoring` | `clusters/homelab/apps/compass` | `IaC/live/argocd-apps/compass` | stateless Kubernetes service discovery dashboard with Octelium service-name launch links and fallback tailnet UI from the `ghcr.io/adinhodovic/charts` OCI Helm source | cert-manager, istio, tailscale, prometheus |
| `descheduler` | `kube-system` | `clusters/homelab/apps/descheduler` | `IaC/live/argocd-apps/descheduler` | controller state only | prometheus |
| `deluge` | `media` | `clusters/homelab/apps/deluge` | `IaC/live/argocd-apps/deluge` | persistent config on `nfs-default`; shared downloads on QNAP `/media`; SSM-backed WireGuard profile via `deluge-vpn` | cert-manager, istio, tailscale, platform-storage |
| `prowlarr` | `media` | `clusters/homelab/apps/prowlarr` | `IaC/live/argocd-apps/prowlarr` | persistent config and PostgreSQL databases | cert-manager, istio, media-postgres, tailscale, platform-storage |
| `radarr` | `media` | `clusters/homelab/apps/radarr` | `IaC/live/argocd-apps/radarr` | persistent config and PostgreSQL databases on `nfs-default`; movies and downloads on QNAP `/media` | cert-manager, istio, tailscale, deluge, media-postgres, prowlarr, platform-storage |
| `sonarr` | `media` | `clusters/homelab/apps/sonarr` | `IaC/live/argocd-apps/sonarr` | persistent config and PostgreSQL databases on `nfs-default`; TV and downloads on QNAP `/media` | cert-manager, istio, tailscale, deluge, media-postgres, prowlarr, platform-storage |
| `litellm` | `ai` | `clusters/homelab/apps/litellm` | `IaC/live/argocd-apps/litellm` | optional persistent config or DB state | external-secrets, cert-manager, istio, tailscale, platform-storage |
| `openclaw` | `ai` | `clusters/homelab/apps/openclaw` | `IaC/live/argocd-apps/openclaw` | persistent runtime state, SSM-backed gateway auth, Discord channel config, SSM-backed GitHub App credentials, Codex OAuth credentials on PVC, and explicit agent resource profile | external-secrets, cert-manager, istio, tailscale, litellm, platform-storage |
| `n8n` | `automation` | `clusters/homelab/apps/n8n` | `IaC/live/argocd-apps/n8n` | persistent workflows, credential metadata, users, and execution history in n8n-postgres; instance settings and file-backed runtime data on PVC; SSM key bootstraps fresh PVCs only; public Funnel is limited to webhook prefixes | external-secrets, cert-manager, istio, tailscale, platform-storage, n8n-postgres |
| `policy-bot` | `automation` | `clusters/homelab/apps/policy-bot` | `IaC/live/argocd-apps/policy-bot` | stateless GitHub App policy evaluator; one replica after SSM placeholders are replaced | external-secrets, cert-manager, istio, tailscale |
| `octobot` | `finance` | `clusters/homelab/apps/octobot` | `IaC/live/argocd-apps/octobot` | UI-configured bot state, tentacles, exchange credentials after operator setup, logs, and Octelium-targeted UI access with tailnet fallback until the e2e gate passes | cert-manager, istio, tailscale, platform-storage |

## Mesh Policy Summary

Istio ambient is committed for the `ai`, `automation`, and `monitoring`
namespaces. The source of truth is `docs/runtime-isolation.md` plus the
`authorizationpolicy.yaml` files in the affected app overlays.

- `ai` uses a namespace default-deny policy and explicit inbound allows for the
  tailnet gateway and Octelium connector to `litellm` and `openclaw`, for
  Alertmanager to reach OpenClaw `/hooks/agent`, and for OpenClaw to reach
  LiteLLM.
- `automation` currently restricts `n8n` workload access to the Istio gateway;
  the reviewed public n8n webhook Funnel forwards into that gateway instead of
  directly to the workload. `n8n-postgres` has a NetworkPolicy that documents
  n8n-only database access, but the current flannel CNI does not enforce
  NetworkPolicy yet. The namespace is not default-denied because Policy Bot
  Funnel traffic and database source-identity validation still need live
  validation after rollout.
- `monitoring` restricts Grafana, Prometheus, Alertmanager, and
  kube-state-metrics by service account. Compass allows only the tailnet gateway,
  Prometheus scraper, and Octelium connector. Compass also owns
  discovery-only `Ingress` resources with an inert `compass-discovery` class;
  those resources intentionally ignore Argo CD health checks because no
  controller populates their load balancer status. The Prometheus operator
  remains unselected until its webhook/control-plane paths are modeled.
- `octelium-client` is ambient-enrolled so the connector has a stable workload
  principal when it calls protected `ai`, `automation`, and `monitoring`
  services.
- `media` stays out of ambient while Deluge Gluetun/WireGuard and the media app
  ingress model need a repo-owned waypoint or equivalent policy design.

## Update Checklist

When a workload changes, update this note for:

- Namespace or path moves.
- New or removed dependencies.
- New ingress host or exposure type.
- New ExternalSecret or SSM parameter contract.
- Persistent storage, backup, restore, or rollback behavior changes.
