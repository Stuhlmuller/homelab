# GitOps Flow

Tags: #architecture #argocd #terragrunt

## Flow

```text
git change
  -> Terragrunt/OpenTofu registration
  -> Argo CD Application
  -> Helm, Kustomize, or repo-owned manifests
  -> Kubernetes cluster state
```

Infrastructure and application registration are modeled through Terragrunt and
OpenTofu. Runtime Kubernetes changes are delivered through Argo CD Applications
that point back at repository-owned manifests, Helm values, or Kustomize
overlays.

`IaC/operator` is the deliberate exception to workflow-driven apply. It owns
bootstrap permissions that the GitHub OIDC role must never change for itself;
an administrator still uses reviewed Terragrunt/OpenTofu desired state and the
shared remote backend to apply those units.

Argo CD Image Updater follows the same review path for repo-declared workload
images: it writes changes to GitHub pull requests instead of keeping live-only
Argo CD parameter overrides as steady state.

## Important Paths

| Concern | Path |
| --- | --- |
| Root Terragrunt settings | `IaC/root.hcl` |
| Argo CD bootstrap | `IaC/bootstrap/argocd` |
| Operator-owned AWS apply-role policy | `IaC/operator/github-actions-role-policy` |
| Argo CD app registrations | `IaC/live/argocd-apps/<app>` |
| Argo CD Application module | `IaC/modules/argocd-application-kubernetes` |
| App desired state | `clusters/homelab/apps/<app>` |
| Platform desired state | `clusters/homelab/platform/<service>` |
| Self-management app source | `clusters/homelab/argocd/self-management` |

See [[runbooks/argocd-bootstrap]], [[runbooks/argocd-app-onboarding]], and
[[runbooks/validation]] for the Obsidian runbook summaries.

## Registration Pattern

Argo CD Applications are registered through the repository-local
`IaC/modules/argocd-application-kubernetes` module. For Git-backed sources that
point at this repository, set `target_revision` to `main` unless a temporary
non-default branch is explicitly documented for testing or recovery.

The module sends repo-owned `spec.sources` values but marks that list as
computed for the Kubernetes provider because Argo CD normalizes multi-source
Application entries after apply. Production logs can therefore include
Terragrunt's internal `tofu apply` subprocess even though the operator entrypoint
remains the Terragrunt workflow or `scripts/ci/terragrunt-apply.sh`.

## Dependency Rule

Terragrunt `dependencies` blocks order Application registration. They do not
prove runtime readiness. A dependency is ready only when Argo CD reports the
upstream Application registered, synced, and healthy, or an exception is
recorded in `docs/validation-runbook.md`.

## Provider Scope

`IaC/root.hcl` owns shared state and inputs, but it does not inject workload
providers into every unit. Kubernetes-backed units include
`IaC/kubernetes-provider.hcl`; the Argo CD bootstrap unit generates its Helm
provider locally. Keep new providers scoped to the units that use them so lock
files represent real module dependencies.

## Source Files

- `docs/argocd-bootstrap.md`
- `docs/argocd-app-onboarding.md`
- `docs/rollback-argocd-apps.md`
- `.agents/skills/terragrunt-workflows/SKILL.md`
