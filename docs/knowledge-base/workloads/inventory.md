# Workload Inventory

Tags: #workloads #argocd #inventory

This inventory summarizes the current application and platform ownership map.
Treat `docs/argocd-app-onboarding.md`, the `clusters/` tree, and Terragrunt
units as the source of truth when they disagree with this note.

## Import Note

This note reflects the current working tree. Human app access for the
`*.stinkyboi.com` app hostnames is through Octelium; Tailscale remains only for
separately reviewed non-app paths such as CI/LAN reachability and webhook
Funnel exceptions.

## Platform And Support Applications

| App | Kind | Namespace | GitOps path | Terragrunt path | Depends on |
| --- | --- | --- | --- | --- | --- |
| `platform-dns` | support | `kube-system` | `clusters/homelab/platform/dns` | `IaC/live/argocd-apps/platform-dns` | Argo CD bootstrap |
| `platform-multus` | support | `kube-system` | `clusters/homelab/platform/multus` | `IaC/live/argocd-apps/platform-multus` | Octelium data-plane prerequisites |
| `platform-storage` | support | cluster-scoped | `clusters/homelab/platform/storage` | `IaC/live/argocd-apps/platform-storage` | QNAP NFS export |
| `octelium-storage` | support | `octelium-storage` | `clusters/homelab/apps/octelium-storage` | `IaC/live/argocd-apps/octelium-storage` | external-secrets, platform-storage |
| `github-actions-runner` | support | `github-actions-runner` | `clusters/homelab/apps/github-actions-runner` | `IaC/live/argocd-apps/github-actions-runner` | external-secrets |
| `media-postgres` | support | `media` | `clusters/homelab/apps/media-postgres` | `IaC/live/argocd-apps/media-postgres` | external-secrets, platform-storage; serves Sonarr, Radarr, Prowlarr, and Dispatcharr databases |
| `n8n-postgres` | support | `automation` | `clusters/homelab/apps/n8n-postgres` | `IaC/live/argocd-apps/n8n-postgres` | external-secrets, platform-storage |

## Requested Applications

| App | Namespace | GitOps path | Terragrunt path | State | Depends on |
| --- | --- | --- | --- | --- | --- |
| `argocd-image-updater` | `argocd` | `clusters/homelab/apps/argocd-image-updater` | `IaC/live/argocd-apps/argocd-image-updater` | controller state and GitHub App PR credential | external-secrets |
| `external-secrets` | `external-secrets` | `clusters/homelab/apps/external-secrets` | `IaC/live/argocd-apps/external-secrets` | controller state only | platform-dns |
| `cert-manager` | `cert-manager` | `clusters/homelab/apps/cert-manager` | `IaC/live/argocd-apps/cert-manager` | controller-managed certificates | external-secrets |
| `istio` | `istio-system` | `clusters/homelab/apps/istio` | `IaC/live/argocd-apps/istio` | controller state only | cert-manager |
| `tailscale` | `tailscale` | `clusters/homelab/apps/tailscale` | `IaC/live/argocd-apps/tailscale` | controller state only | external-secrets, istio |
| `octelium-cluster` | `istio-system` | `clusters/homelab/apps/octelium-cluster` | `IaC/live/argocd-apps/octelium-cluster` | Istio front-proxy route for the self-hosted Octelium Cluster domain, portal, API hostnames, and direct Enterprise console hostname, plus an HTTP/2 upstream `DestinationRule` so Octelium CLI gRPC calls keep response trailers; the Octelium runtime namespace and workloads are installed by `scripts/octelium-cluster-bootstrap.sh` through `octops`, and the wrapper labels that namespace for privileged data-plane pods | istio, platform-multus, octelium-storage |
| `octelium-public` | `octelium-public` | `clusters/homelab/apps/octelium-public` | `IaC/live/argocd-apps/octelium-public` | stateless Cloudflare Tunnel connector for public Octelium Cluster/API/portal, app clientless access, and the Enterprise console; reads `/homelab/octelium/cloudflare-tunnel-credentials-json`, uses QUIC tunnel transport for long-lived Octelium API gRPC streams, forwards `stinkyboi.com`, `octelium.stinkyboi.com`, `portal.stinkyboi.com`, `octelium-api.stinkyboi.com`, and `console.stinkyboi.com` through the in-cluster Istio gateway, and forwards app hostnames such as `grafana.stinkyboi.com` directly to the Octelium ingress dataplane | external-secrets, istio, octelium-cluster |
| `octelium` | `octelium-client` | `clusters/homelab/apps/octelium` | `IaC/live/argocd-apps/octelium` | stateless TUN-mode Octelium client bridge pinned to Octelium dataplane nodes and target human app access plane for Cluster domain `stinkyboi.com`; the explicit homelab app Service catalog maps existing `*.stinkyboi.com` app hostnames to public Octelium `WEB` Services that enforce clientless browser login before proxying to the Istio gateway, while Podinfo remains as a demo service; auth token is `/homelab/octelium/client-auth-token`; portal login uses Entra IdentityProvider `entra` from `IaC/live/azuread-applications/octelium` and `scripts/octelium-entra-oidc.sh`; cutover is gated by `scripts/octelium-e2e-check.sh` | external-secrets, istio |
| `octelium-enterprise` | `octelium` | `clusters/homelab/apps/octelium-enterprise` | `IaC/live/argocd-apps/octelium-enterprise` | Argo CD-owned Kubernetes steady state for Enterprise package `octeliumee` `0.22.0` after `scripts/octelium-enterprise-package.sh` install or upgrade; owns package Deployments, Services, ConfigMaps, ServiceAccounts, and PVC declarations for `octelium-rscstore`, `octelium-logstore`, and `octelium-metricstore`; ignores only controller-normalized generated service-proxy image fields; generated Secrets and license material stay outside git | octelium-cluster, octelium-storage, platform-storage |
| `cordium` | `octelium` | `clusters/homelab/apps/cordium` | `IaC/live/argocd-apps/cordium` | Cordium `0.12.7` genesis hook; genesis creates Cordium controller pods and Octelium managed services, browser access is `https://cordium.stinkyboi.com` through the Octelium `cordium` WEB Service, workspace app subdomains route through `*.cordium.stinkyboi.com`, and agent automation uses the separate `homelab-cordium-agent` WORKLOAD identity with `cordium-agent-api.homelab` | octelium-cluster, octelium-enterprise |
| `prometheus` | `monitoring` | `clusters/homelab/apps/prometheus` | `IaC/live/argocd-apps/prometheus` | persistent metrics, Alertmanager state, Argo CD scrape config, and Alertmanager Discord/OpenClaw notification secrets | external-secrets, platform-storage |
| `grafana` | `monitoring` | `clusters/homelab/apps/grafana` | `IaC/live/argocd-apps/grafana` | persistent config, dashboards, platform/workload alert rules, expected hardware-node and Kubernetes-node alerting, public GitHub API PR/status polling, and stale direct receiver cleanup | external-secrets, cert-manager, istio, prometheus, platform-storage |
| `kiali` | `monitoring` | `clusters/homelab/apps/kiali` | `IaC/live/argocd-apps/kiali` | controller state only; read-only mesh UI through Octelium app access | istio, prometheus, grafana |
| `compass` | `monitoring` | `clusters/homelab/apps/compass` | `IaC/live/argocd-apps/compass` | stateless Kubernetes service discovery dashboard with Octelium service-name launch links from the `ghcr.io/adinhodovic/charts` OCI Helm source | cert-manager, istio, prometheus |
| `descheduler` | `kube-system` | `clusters/homelab/apps/descheduler` | `IaC/live/argocd-apps/descheduler` | controller state only | prometheus |
| `deluge` | `media` | `clusters/homelab/apps/deluge` | `IaC/live/argocd-apps/deluge` | persistent config on `nfs-default`; shared downloads on QNAP `/media`; SSM-backed WireGuard profile via `deluge-vpn` | cert-manager, istio, platform-storage |
| `dispatcharr` | `media` | `clusters/homelab/apps/dispatcharr` | `IaC/live/argocd-apps/dispatcharr` | persistent modular IPTV stream and EPG manager state on `nfs-default` plus dedicated `dispatcharr-postgres`; Octelium-targeted UI access; provider credentials and playlist URLs stay UI-configured or future ExternalSecret-backed, not committed | external-secrets, cert-manager, istio, dispatcharr-postgres, platform-storage |
| `prowlarr` | `media` | `clusters/homelab/apps/prowlarr` | `IaC/live/argocd-apps/prowlarr` | persistent config and PostgreSQL databases | cert-manager, istio, media-postgres, platform-storage |
| `radarr` | `media` | `clusters/homelab/apps/radarr` | `IaC/live/argocd-apps/radarr` | persistent config and PostgreSQL databases on `nfs-default`; movies and downloads on QNAP `/media` | cert-manager, istio, deluge, media-postgres, prowlarr, platform-storage |
| `sonarr` | `media` | `clusters/homelab/apps/sonarr` | `IaC/live/argocd-apps/sonarr` | persistent config and PostgreSQL databases on `nfs-default`; TV and downloads on QNAP `/media` | cert-manager, istio, deluge, media-postgres, prowlarr, platform-storage |
| `litellm` | `ai` | `clusters/homelab/apps/litellm` | `IaC/live/argocd-apps/litellm` | optional persistent config or DB state | external-secrets, cert-manager, istio, platform-storage |
| `openclaw` | `ai` | `clusters/homelab/apps/openclaw` | `IaC/live/argocd-apps/openclaw` | persistent runtime state, SSM-backed gateway auth, Discord channel config, SSM-backed GitHub App credentials, Codex OAuth credentials on PVC, and explicit agent resource profile | external-secrets, cert-manager, istio, litellm, platform-storage |
| `n8n` | `automation` | `clusters/homelab/apps/n8n` | `IaC/live/argocd-apps/n8n` | persistent workflows, credential metadata, users, and execution history in n8n-postgres; instance settings and file-backed runtime data on PVC; SSM key bootstraps fresh PVCs only; public Funnel is limited to webhook prefixes | external-secrets, cert-manager, istio, tailscale, platform-storage, n8n-postgres |
| `policy-bot` | `automation` | `clusters/homelab/apps/policy-bot` | `IaC/live/argocd-apps/policy-bot` | stateless GitHub App policy evaluator; one replica after SSM placeholders are replaced | external-secrets, cert-manager, istio, tailscale |
| `octobot` | `finance` | `clusters/homelab/apps/octobot` | `IaC/live/argocd-apps/octobot` | UI-configured bot state, tentacles, exchange credentials after operator setup, logs, and Octelium-targeted UI access | cert-manager, istio, platform-storage |

## Mesh Policy Summary

Istio ambient is committed for the `ai`, `automation`, and `monitoring`
namespaces. The source of truth is `docs/runtime-isolation.md` plus the
`authorizationpolicy.yaml` files in the affected app overlays.

- `ai` uses a namespace default-deny policy and explicit inbound allows for the
  Istio gateway path used by Octelium service proxies, the Octelium connector
  principal reserved for future served upstreams, Alertmanager to reach
  OpenClaw `/hooks/agent`, and OpenClaw to reach LiteLLM.
- `automation` currently restricts `n8n` workload access to the Istio gateway;
  the reviewed public n8n webhook Funnel forwards into that gateway instead of
  directly to the workload. `n8n-postgres` has a NetworkPolicy that documents
  n8n-only database access, but the current flannel CNI does not enforce
  NetworkPolicy yet. The namespace is not default-denied because Policy Bot
  Funnel traffic and database source-identity validation still need live
  validation after rollout.
- `monitoring` restricts Grafana, Prometheus, Alertmanager, and
  kube-state-metrics by service account. Compass allows only the Istio gateway
  path used by Octelium service proxies, Prometheus scraper, and Octelium
  connector. Compass also owns
  discovery-only `Ingress` resources with an inert `compass-discovery` class;
  those resources intentionally ignore Argo CD health checks because no
  controller populates their load balancer status. The Prometheus operator
  remains unselected until its webhook/control-plane paths are modeled.
- `octelium-client` is ambient-enrolled so future connector-served upstreams
  have a stable workload principal when they call protected `ai`, `automation`,
  and `monitoring` services.
- `media` stays out of ambient while Deluge Gluetun/WireGuard and the media app
  ingress model need a repo-owned waypoint or equivalent policy design.

## Update Checklist

When a workload changes, update this note for:

- Namespace or path moves.
- New or removed dependencies.
- New ingress host or exposure type.
- New ExternalSecret or SSM parameter contract.
- Persistent storage, backup, restore, or rollback behavior changes.
