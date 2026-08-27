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
Argo CD globally terminates sync operations after 15 minutes so one unhealthy
resource cannot hold an Application operation forever and block later reviewed
revisions.
The bootstrap chart carries a revision annotation on the application-controller
Pod so command-parameter changes restart the controller and take effect.

`IaC/operator` is the deliberate exception to workflow-driven apply. It owns
bootstrap permissions that the GitHub OIDC role must never change for itself;
an administrator still uses reviewed Terragrunt/OpenTofu desired state and the
shared remote backend to apply those units.

Octelium recovery has one transport exception, not a desired-state exception:
a trusted LAN operator may apply the reviewed `kubernetes-node-labels`
Terragrunt unit through the canonical private API and shared remote backend when
GitHub-hosted runners cannot reach that API through Octelium. The repository
unit, saved plan, policy check, and normal Terragrunt state remain authoritative;
no ad hoc Kubernetes mutation or GitHub kubeconfig secret is introduced.

Renovate owns repo-declared workload image updates through reviewed pull
requests. Static policy requires every committed image to keep a digest pin;
live-only Argo CD parameter overrides are not steady state.

Cordium's CLI-native `ClusterConfig` is packaged into a generated ConfigMap and
applied by an Argo CD PostSync hook after the upstream genesis hook completes.
This keeps the non-Kubernetes API resource on the same reviewed GitOps path.
Its ConfigMap generator annotation is the narrow rerun trigger when only that
hook needs reconciliation.
The Cordium Application is allowed to deploy control resources to `octelium`
and workspace support resources to the dedicated `cordium` namespace.
The Cordium Application prunes removed repository-owned Kubernetes manifests;
Cordium and Octelium resources generated through their native APIs remain
outside Argo CD's tracking and are unaffected by that setting.

## Important Paths

| Concern | Path |
| --- | --- |
| Root Terragrunt settings | `IaC/root.hcl` |
| Terragrunt stack entry point | `IaC/terragrunt.stack.hcl` |
| Terragrunt unit templates | `IaC/.catalog/units` |
| Generated Argo CD bootstrap unit | `IaC/bootstrap/argocd` |
| Operator AWS apply-role policy | `IaC/operator/github-actions-role-policy` |
| Generated Argo CD app registrations | `IaC/live/argocd-apps/<app>` |
| Argo CD Application module | `IaC/modules/argocd-application-kubernetes` |
| App desired state | `clusters/homelab/apps/<app>` |
| Platform desired state | `clusters/homelab/platform/<service>` |
| Self-management app source | `clusters/homelab/argocd/self-management` |

See [[runbooks/argocd-bootstrap]], [[runbooks/argocd-app-onboarding]], and
[[runbooks/validation]] for the Obsidian runbook summaries.

## Registration Pattern

Argo CD Applications are registered through the shared Terragrunt unit template
at `IaC/.catalog/units/live/argocd-app` and per-app `values` in the explicit
stack at `IaC/terragrunt.stack.hcl`. The generated units keep the historical
`IaC/live/...` paths so S3 backend keys remain stable. The template sources the
repository-local `IaC/modules/argocd-application-kubernetes` module and passes a
raw CRD-shaped `manifest`, so Application fields use their native names such as
`repoURL`, `targetRevision`, and `syncPolicy`. For Git-backed sources that point
at this repository, set `targetRevision` to `main` unless a temporary
non-default branch is explicitly documented for testing or recovery.

The module delegates the CRD schema to `kubernetes_manifest` while retaining
repository policy for encrypted state, field-manager ownership, and the small
set of fields Argo CD or the API server normalizes. Repository-owned source
fields remain declarative. Production logs can include Terragrunt's internal
`tofu apply` subprocess even though the operator entrypoint remains the
Terragrunt workflow or `scripts/ci/terragrunt-apply.sh`.

Confirmed tainted Application state is repaired through the protected
`Terragrunt Apply` dispatch with one exact `argocd_app` and
`repair_argocd_app_state=true`. That path untaints only
`kubernetes_manifest.this`, then reuses the normal policy-checked exact-unit
plan and saved-plan apply; it does not expose a generic state mutation input.

Ordinary workloads use the `homelab-workloads` AppProject when their rendered
resources need no cluster scope. Its first tranche is Dispatcharr, OpenClaw,
Policy Bot, and Prowlarr. Platform controllers, namespace-owning applications,
and applications with audited cluster-resource requirements remain in the
`homelab` project. `n8n-postgres` remains there because its existing managed
namespace metadata requires access to the cluster-scoped `automation`
Namespace.

`platform-crossplane` currently installs only Crossplane core through the
upstream Helm chart. Before Argo CD owns Crossplane Provider, Composition, or
managed-resource manifests, add the Crossplane-recommended Argo CD tracking and
health settings to the repository-owned Argo CD configuration.

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
