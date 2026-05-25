# Argo CD App Onboarding

This feature registers 14 requested homelab applications plus one supporting
`platform-storage` Application. The support app owns the QNAP-backed NFS
provisioner and default StorageClass desired state and is not counted as a
requested workload.

## Applications

| App | Kind | Namespace | GitOps path | Terragrunt path | Auto-sync | Dependencies |
|-----|------|-----------|-------------|-----------------|-----------|--------------|
| platform-storage | support | cluster-scoped | `clusters/homelab/platform/storage` | `IaC/live/argocd-apps/platform-storage` | Yes | QNAP NFS export validation |
| argocd-image-updater | requested | `argocd` | `clusters/homelab/apps/argocd-image-updater` | `IaC/live/argocd-apps/argocd-image-updater` | Yes | Argo CD bootstrap |
| external-secrets | requested | `external-secrets` | `clusters/homelab/apps/external-secrets` | `IaC/live/argocd-apps/external-secrets` | Yes | Argo CD bootstrap |
| cert-manager | requested | `cert-manager` | `clusters/homelab/apps/cert-manager` | `IaC/live/argocd-apps/cert-manager` | Yes | external-secrets |
| istio | requested | `istio-system` | `clusters/homelab/apps/istio` | `IaC/live/argocd-apps/istio` | Yes | cert-manager |
| tailscale | requested | `tailscale` | `clusters/homelab/apps/tailscale` | `IaC/live/argocd-apps/tailscale` | Yes | external-secrets, istio |
| prometheus | requested | `monitoring` | `clusters/homelab/apps/prometheus` | `IaC/live/argocd-apps/prometheus` | Yes | external-secrets, platform-storage |
| grafana | requested | `monitoring` | `clusters/homelab/apps/grafana` | `IaC/live/argocd-apps/grafana` | Yes | external-secrets, cert-manager, istio, tailscale, prometheus, platform-storage |
| descheduler | requested | `kube-system` | `clusters/homelab/apps/descheduler` | `IaC/live/argocd-apps/descheduler` | Yes | prometheus |
| deluge | requested | `media` | `clusters/homelab/apps/deluge` | `IaC/live/argocd-apps/deluge` | Yes | cert-manager, istio, tailscale, platform-storage |
| radarr | requested | `media` | `clusters/homelab/apps/radarr` | `IaC/live/argocd-apps/radarr` | Yes | cert-manager, istio, tailscale, deluge, platform-storage |
| sonarr | requested | `media` | `clusters/homelab/apps/sonarr` | `IaC/live/argocd-apps/sonarr` | Yes | cert-manager, istio, tailscale, deluge, platform-storage |
| litellm | requested | `ai` | `clusters/homelab/apps/litellm` | `IaC/live/argocd-apps/litellm` | Yes | external-secrets, cert-manager, istio, tailscale, platform-storage |
| openclaw | requested | `ai` | `clusters/homelab/apps/openclaw` | `IaC/live/argocd-apps/openclaw` | Yes | external-secrets, cert-manager, istio, tailscale, litellm, platform-storage |
| tines | requested | `automation` | `clusters/homelab/apps/tines` | `IaC/live/argocd-apps/tines` | Yes | external-secrets, cert-manager, istio, tailscale, platform-storage |

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

## Registration Provider

Terragrunt registers Applications through the repository-local
`IaC/modules/argocd-application-kubernetes` module. The module writes Argo CD
`Application` CRDs through the Kubernetes provider, so routine registration does
not require an exposed Argo CD API endpoint, an auth token in operator
environment variables, or a manual local `argocd login`.

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
