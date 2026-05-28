# Source Map

Tags: #knowledge-base #source-map

This vault summarizes repository source files; it does not replace them. Use
this map to jump from Obsidian notes back to canonical files before changing
desired state.

## Top-Level Guidance

| Source | Vault note | Purpose |
| --- | --- | --- |
| `AGENTS.md` | [[operations/continuous-improvement]] | Agent workflow, safety boundaries, ownership, ongoing stewardship |
| `ONBOARDING.md` | [[runbooks/homelab-onboarding]] | Talos and cluster onboarding |

## Runbooks

| Source | Vault note |
| --- | --- |
| `docs/argocd-bootstrap.md` | [[runbooks/argocd-bootstrap]] |
| `docs/argocd-app-onboarding.md` | [[runbooks/argocd-app-onboarding]] |
| `docs/argocd-image-updater.md` | [[runbooks/image-automation]] |
| `docs/ci-cd.md` | [[runbooks/ci-cd]] |
| `docs/networking-tailnet-ingress.md` | [[runbooks/tailnet-ingress]] |
| `docs/rollback-argocd-apps.md` | [[runbooks/rollback]] |
| `docs/runtime-isolation.md` | [[runbooks/runtime-isolation]] |
| `docs/secrets-aws-ssm.md` | [[runbooks/secrets-aws-ssm]] |
| `docs/storage-nfs.md` | [[runbooks/storage-nfs]] |
| `docs/talos-control-plane-maintenance.md` | [[runbooks/talos-control-plane-maintenance]] |
| `docs/validation-runbook.md` | [[runbooks/validation]] |

## App And Platform Notes

| Source | Vault note |
| --- | --- |
| `clusters/homelab/apps/README.md` | [[workloads/application-notes]] |
| `clusters/homelab/apps/*/README.md` | [[workloads/application-notes]] |
| `clusters/homelab/platform/*/README.md` | [[workloads/application-notes]] |
| `IaC/live/argocd-apps/README.md` | [[runbooks/argocd-app-onboarding]] |

## Spec Artifacts

The `specs/001-onboard-argocd-apps/` artifacts remain useful for design intent
and acceptance criteria. Prefer the current runbooks and source paths for
operator commands because the working tree may have moved since the spec was
generated.
