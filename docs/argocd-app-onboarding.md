# Argo CD App Onboarding

This feature registers requested homelab applications plus supporting
Applications for shared platform dependencies. `platform-dns` owns CoreDNS
resolver policy, `platform-storage` owns the QNAP-backed NFS provisioner and
default StorageClass desired state, and `media-postgres` owns the shared
PostgreSQL instance for Sonarr, Radarr, and Prowlarr. `n8n-postgres` owns the
dedicated PostgreSQL instance for n8n. These support apps are not counted as
requested workloads.

## Applications

| App | Kind | Namespace | GitOps path | Terragrunt path | Auto-sync | Dependencies |
|-----|------|-----------|-------------|-----------------|-----------|--------------|
| platform-dns | support | `kube-system` | `clusters/homelab/platform/dns` | `IaC/live/argocd-apps/platform-dns` | Yes, no prune | Argo CD bootstrap |
| platform-storage | support | cluster-scoped | `clusters/homelab/platform/storage` | `IaC/live/argocd-apps/platform-storage` | Yes | QNAP NFS export validation |
| media-postgres | support | `media` | `clusters/homelab/apps/media-postgres` | `IaC/live/argocd-apps/media-postgres` | Yes | external-secrets, platform-storage |
| n8n-postgres | support | `automation` | `clusters/homelab/apps/n8n-postgres` | `IaC/live/argocd-apps/n8n-postgres` | Yes | external-secrets, platform-storage |
| github-actions-runner | support | `github-actions-runner` | `clusters/homelab/apps/github-actions-runner` | `IaC/live/argocd-apps/github-actions-runner` | Yes | external-secrets |
| argocd-image-updater | requested | `argocd` | `clusters/homelab/apps/argocd-image-updater` | `IaC/live/argocd-apps/argocd-image-updater` | Yes | external-secrets |
| external-secrets | requested | `external-secrets` | `clusters/homelab/apps/external-secrets` | `IaC/live/argocd-apps/external-secrets` | Yes | platform-dns |
| cert-manager | requested | `cert-manager` | `clusters/homelab/apps/cert-manager` | `IaC/live/argocd-apps/cert-manager` | Yes | external-secrets |
| istio | requested | `istio-system` | `clusters/homelab/apps/istio` | `IaC/live/argocd-apps/istio` | Yes | cert-manager |
| tailscale | requested | `tailscale` | `clusters/homelab/apps/tailscale` | `IaC/live/argocd-apps/tailscale` | Yes | external-secrets, istio |
| octelium | requested | `octelium-client` | `clusters/homelab/apps/octelium` | `IaC/live/argocd-apps/octelium` | Yes | external-secrets, istio |
| octelium-enterprise | requested | `octelium` | `clusters/homelab/apps/octelium-enterprise` | `IaC/live/argocd-apps/octelium-enterprise` | Yes | octelium-cluster, octelium-storage, platform-storage |
| prometheus | requested | `monitoring` | `clusters/homelab/apps/prometheus` | `IaC/live/argocd-apps/prometheus` | Yes | external-secrets, platform-storage |
| grafana | requested | `monitoring` | `clusters/homelab/apps/grafana` | `IaC/live/argocd-apps/grafana` | Yes | external-secrets, cert-manager, istio, prometheus, platform-storage |
| kiali | requested | `monitoring` | `clusters/homelab/apps/kiali` | `IaC/live/argocd-apps/kiali` | Yes | istio, prometheus, grafana |
| compass | requested | `monitoring` | `clusters/homelab/apps/compass` | `IaC/live/argocd-apps/compass` | Yes | cert-manager, istio, prometheus |
| descheduler | requested | `kube-system` | `clusters/homelab/apps/descheduler` | `IaC/live/argocd-apps/descheduler` | Yes | prometheus |
| deluge | requested | `media` | `clusters/homelab/apps/deluge` | `IaC/live/argocd-apps/deluge` | Yes | cert-manager, istio, platform-storage |
| dispatcharr | requested | `media` | `clusters/homelab/apps/dispatcharr` | `IaC/live/argocd-apps/dispatcharr` | Yes | cert-manager, istio, platform-storage |
| prowlarr | requested | `media` | `clusters/homelab/apps/prowlarr` | `IaC/live/argocd-apps/prowlarr` | Yes | cert-manager, istio, media-postgres, platform-storage |
| radarr | requested | `media` | `clusters/homelab/apps/radarr` | `IaC/live/argocd-apps/radarr` | Yes | cert-manager, istio, deluge, media-postgres, prowlarr, platform-storage |
| sonarr | requested | `media` | `clusters/homelab/apps/sonarr` | `IaC/live/argocd-apps/sonarr` | Yes | cert-manager, istio, deluge, media-postgres, prowlarr, platform-storage |
| litellm | requested | `ai` | `clusters/homelab/apps/litellm` | `IaC/live/argocd-apps/litellm` | Yes | external-secrets, cert-manager, istio, platform-storage |
| openclaw | requested | `ai` | `clusters/homelab/apps/openclaw` | `IaC/live/argocd-apps/openclaw` | Yes | external-secrets, cert-manager, istio, litellm, platform-storage |
| n8n | requested | `automation` | `clusters/homelab/apps/n8n` | `IaC/live/argocd-apps/n8n` | Yes | external-secrets, cert-manager, istio, tailscale, platform-storage, n8n-postgres |
| policy-bot | requested | `automation` | `clusters/homelab/apps/policy-bot` | `IaC/live/argocd-apps/policy-bot` | Yes | external-secrets, cert-manager, istio, tailscale |
| octobot | requested | `finance` | `clusters/homelab/apps/octobot` | `IaC/live/argocd-apps/octobot` | Yes | cert-manager, istio, platform-storage |

## Dependency Readiness

`dependencies` blocks in Terragrunt order Argo CD Application registration.
They do not prove runtime readiness by themselves. An app is considered
available for a dependent app only after:

1. The upstream Argo CD Application is registered by Terragrunt.
2. Argo CD reports the upstream app `Synced`.
3. Argo CD reports the upstream app `Healthy`, or an exception is recorded in
   `docs/validation-runbook.md`.

Stateful apps auto-sync by default, but they are not considered operationally
ready until `platform-storage` is synced, the `nfs-default` StorageClass is
verified, and `docs/storage-nfs.md` records backup coverage.

Deluge, Radarr, and Sonarr keep app config on `nfs-default`, but media library
paths use static claims against the QNAP `/media` export. Read-only
`showmount -e 10.1.0.2` verified `/media` for every Talos node on 2026-05-26;
do not treat those apps as cut over until the three media migration Jobs have
completed.

Sonarr, Radarr, and Prowlarr are also not considered ready until
`media-postgres` is synced, the `media-postgres-auth` and
`media-postgres-arr-env` ExternalSecrets are ready, the six logical databases
exist, each app's `config.xml` contains the official Servarr PostgreSQL fields,
and any required SQLite-to-PostgreSQL data migration has been completed.

n8n is not considered ready until `n8n-postgres` is synced and healthy, the
`n8n-postgres-auth` and `n8n-postgres-client` ExternalSecrets are ready, the
`n8n` database exists, and any required SQLite export/import migration has been
completed.

## Registration Provider

Terragrunt registers Applications through the repository-local
`IaC/modules/argocd-application-kubernetes` module. The module writes Argo CD
`Application` CRDs through the Kubernetes provider, so routine registration does
not require an exposed Argo CD API endpoint, an auth token in operator
environment variables, or a manual local `argocd login`.

## Image Updates

Repo-declared workload images are managed by Argo CD Image Updater through
`clusters/homelab/apps/argocd-image-updater/imageupdater.yaml`. Image updates
use Git write-back pull requests against `main`; do not add live-only Argo CD
parameter overrides for image drift.

## Sync And Health Exception Record

Use this format for every exception:

```text
App:
Observed status:
Blocking dependency:
Operator action:
Rollback decision:
Follow-up issue or PR:
```
