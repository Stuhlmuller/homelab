# New Application Pattern

Tags: #pattern #argocd #workload

Use this checklist before adding a new runtime application.

## Read First

- [[architecture/gitops-flow]]
- [[architecture/storage-and-state]]
- [[architecture/secrets-and-identity]]
- [[workloads/inventory]]
- `docs/argocd-app-onboarding.md`
- `docs/networking-tailnet-ingress.md` when adding ingress
- `docs/storage-nfs.md` when adding persistent state
- `docs/secrets-aws-ssm.md` when adding runtime secrets

## Implementation Shape

1. Add app desired state under `clusters/homelab/apps/<app>`.
2. Register the Application under `IaC/live/argocd-apps/<app>`.
3. Use `main` as the target revision for Git-backed sources unless a temporary
   branch is explicitly documented.
4. Add Terragrunt dependencies for registration ordering.
5. Add runtime readiness notes for dependencies that must be synced and healthy.
6. Keep non-secret desired-state inputs in committed files.
7. Use ExternalSecret and SSM parameter references for secret material.
8. Document persistent storage, backup, and restore behavior before considering
   the app production-ready.

## Ingress Rule

Tailnet-only ingress is the default. Public Funnel or public HTTP exposure must
be intentional, reviewed, and documented with authentication or signature
checks, data exposure, and rollback steps.

## Knowledge-Base Update

Update [[workloads/inventory]], any affected architecture note, and
[[operations/change-log]] in the same change.
