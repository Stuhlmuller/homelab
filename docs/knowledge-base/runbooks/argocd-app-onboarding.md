# Argo CD App Onboarding

Tags: #runbooks #argocd #apps #terragrunt

Sources:

- `docs/argocd-app-onboarding.md`
- `IaC/live/argocd-apps/README.md`

## Registration Model

Each child directory under `IaC/live/argocd-apps` owns one Argo CD Application
registration and sources the repository-local
`IaC/modules/argocd-application-kubernetes` module. Runtime desired state lives
under `clusters/homelab/apps/<app>` or `clusters/homelab/platform/<service>`.

The current app onboarding runbook includes the requested apps plus support
Applications. Kiali is the read-only Istio mesh UI, and OctoBot is the current
finance namespace app. Hummingbot remains as a retired PVC-only Application for
rollback data, and Freqtrade is historical unless a future change reintroduces
it.

## Support Applications

| App | Purpose |
| --- | --- |
| `platform-dns` | CoreDNS resolver policy |
| `platform-storage` | QNAP NFS provisioner and default StorageClass |
| `media-postgres` | Shared PostgreSQL for Sonarr, Radarr, and Prowlarr |

## Conventions

- One `terragrunt.hcl` per Application.
- Include `IaC/root.hcl` from every unit.
- Use the local Kubernetes-backed Application module.
- Register Applications in the `homelab` AppProject.
- Update `clusters/homelab/argocd/self-management/appproject.yaml` before an
  app needs a new chart repo, namespace, destination, or cluster-scoped kind.
- Declare upstream relationships with `dependencies`.
- Use automated sync with prune and self-heal by default; document exceptions.
- Keep non-secret values and raw manifests under repo-owned app/platform paths.
- Manage repo-declared workload image updates through
  `clusters/homelab/apps/argocd-image-updater/imageupdater.yaml`, which opens
  GitHub pull requests through Git write-back.

## Readiness Semantics

Terragrunt dependencies order registration only. A dependency is operationally
ready only after Argo CD reports it registered, synced, and healthy, or an
exception is recorded in `docs/validation-runbook.md`.

Stateful apps are not production-ready until `platform-storage`, `nfs-default`,
PVC validation, and backup expectations are all satisfied.

Sonarr, Radarr, and Prowlarr additionally require `media-postgres`,
`media-postgres-auth`, `media-postgres-arr-env`, six logical databases, and the
official Servarr PostgreSQL `config.xml` fields.

## Related Notes

- [[../workloads/inventory]]
- [[../workloads/application-notes]]
- [[new-application]]
- [[validation]]
- [[rollback]]
