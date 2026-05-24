# Argo CD App Onboarding

This feature registers 13 requested homelab applications plus one supporting
`platform-storage` Application. The support app owns the default NFS
StorageClass desired state and is not counted as a requested workload.

## Applications

| App | Kind | Namespace | GitOps path | Terragrunt path | Auto-sync | Dependencies |
|-----|------|-----------|-------------|-----------------|-----------|--------------|
| platform-storage | support | cluster-scoped | `clusters/homelab/platform/storage` | `IaC/live/argocd-apps/platform-storage` | No | Existing NFS provisioner prerequisite |
| external-secrets | requested | `external-secrets` | `clusters/homelab/apps/external-secrets` | `IaC/live/argocd-apps/external-secrets` | Yes | Argo CD bootstrap |
| cert-manager | requested | `cert-manager` | `clusters/homelab/apps/cert-manager` | `IaC/live/argocd-apps/cert-manager` | Yes | external-secrets |
| istio | requested | `istio-system` | `clusters/homelab/apps/istio` | `IaC/live/argocd-apps/istio` | Yes | cert-manager |
| tailscale | requested | `tailscale` | `clusters/homelab/apps/tailscale` | `IaC/live/argocd-apps/tailscale` | Yes | external-secrets, istio |
| prometheus | requested | `monitoring` | `clusters/homelab/apps/prometheus` | `IaC/live/argocd-apps/prometheus` | No | external-secrets, platform-storage |
| grafana | requested | `monitoring` | `clusters/homelab/apps/grafana` | `IaC/live/argocd-apps/grafana` | No | external-secrets, cert-manager, istio, tailscale, prometheus, platform-storage |
| descheduler | requested | `kube-system` | `clusters/homelab/apps/descheduler` | `IaC/live/argocd-apps/descheduler` | Yes | prometheus |
| deluge | requested | `media` | `clusters/homelab/apps/deluge` | `IaC/live/argocd-apps/deluge` | No | external-secrets, cert-manager, istio, tailscale, platform-storage |
| radarr | requested | `media` | `clusters/homelab/apps/radarr` | `IaC/live/argocd-apps/radarr` | No | external-secrets, cert-manager, istio, tailscale, deluge, platform-storage |
| sonarr | requested | `media` | `clusters/homelab/apps/sonarr` | `IaC/live/argocd-apps/sonarr` | No | external-secrets, cert-manager, istio, tailscale, deluge, platform-storage |
| litellm | requested | `ai` | `clusters/homelab/apps/litellm` | `IaC/live/argocd-apps/litellm` | No | external-secrets, cert-manager, istio, tailscale, platform-storage |
| openclaw | requested | `ai` | `clusters/homelab/apps/openclaw` | `IaC/live/argocd-apps/openclaw` | No | external-secrets, cert-manager, istio, tailscale, litellm, platform-storage |
| tines | requested | `automation` | `clusters/homelab/apps/tines` | `IaC/live/argocd-apps/tines` | No | external-secrets, cert-manager, istio, tailscale, platform-storage |

## Dependency Readiness

`dependencies` blocks in Terragrunt order Argo CD Application registration.
They do not prove runtime readiness by themselves. An app is considered
available for a dependent app only after:

1. The upstream Argo CD Application is registered by Terragrunt.
2. Argo CD reports the upstream app `Synced`.
3. Argo CD reports the upstream app `Healthy`, or an exception is recorded in
   `docs/validation-runbook.md`.

Stateful apps remain manual-sync until `docs/storage-nfs.md` records an
available NFS provisioner and backup coverage.

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

