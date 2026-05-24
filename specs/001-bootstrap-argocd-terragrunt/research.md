# Research: Bootstrap Argo CD With Terragrunt

## Decision: Source The Terragrunt Catalog Module Remotely

Use the catalog-discovered Helm module directly from the configured
`terragrunt-catalog` repository pinned at version `0.3.0`:

```text
git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/helm-release?ref=0.3.0
```

The `0.3.0` tag points at commit
`415f4ec587846f6928aeb344cd9e46f66c16a005`, which contains the platform
resource modules needed by this feature.

**Rationale**: The constitution requires repo-owned, reviewable desired state
and modular short input surfaces. The user clarified that repository-local
modules should not be used, so the module implementation remains in the catalog
and this repository owns the pinned source and committed inputs.

**Alternatives considered**:

- Scaffold catalog modules into `IaC/modules/`. Rejected after user
  clarification because the bootstrap should use catalog version `0.3.0`
  directly.
- Hand-write a local composite module. Rejected because it would violate the
  no-local-modules constraint.

## Decision: One Composite Terragrunt Entry Point

Create one Terragrunt unit at `IaC/bootstrap/argocd/terragrunt.hcl` that points
at the catalog `helm-release` module. The unit installs Argo CD with Helm and
then uses a Terragrunt `after_hook` to wait for `applications.argoproj.io`
before applying the repo-owned self-management Application manifest.

For clean clusters, this avoids asking the Kubernetes provider to plan an
Application CRD before it exists and avoids Helm creating a custom resource
before discovery recognizes the newly installed CRD.

**Rationale**: This preserves the one-command bootstrap target while still
respecting the required resource order: Argo CD CRDs must exist before the
Application CRD is planned/applied.

**Alternatives considered**:

- Two independent Terragrunt units applied manually in sequence. Rejected
  because it weakens the one-command-from-scratch target.
- Argo CD installed manually first. Rejected because manual live setup would not
  be durable repository state.

## Decision: Terragrunt Seeds, Argo CD Owns Steady State

Terragrunt owns only the initial Argo CD installation and self-management
registration. After handoff, Argo CD owns steady-state Argo CD configuration
from repository desired state.

**Rationale**: This matches the clarified feature intent and avoids split
long-term ownership where both Terragrunt and Argo CD might fight over the same
Kubernetes resources.

**Alternatives considered**:

- Terragrunt permanently owns Argo CD. Rejected because it contradicts the
  "Argo CD into Argo CD" goal.
- Assume an existing manual Argo CD install. Rejected because the bootstrap must
  work from a clean cluster with documented prerequisites.

## Decision: Validate First Handoff Before Automated Prune/Self-Heal

The initial self-management Application should be created in a safe handoff
mode. Operators validate the first sync and then enable automated prune and
self-heal through a repository-owned desired-state change.

**Rationale**: Self-management can remove or overwrite control-plane delivery
resources if the source path is wrong. A validated first handoff reduces the
highest-impact bootstrap failure mode while preserving the eventual automated
GitOps posture.

**Alternatives considered**:

- Enable automated prune and self-heal immediately. Rejected for initial
  bootstrap because a wrong path or namespace can cause fast destructive drift.
- Keep manual sync forever. Rejected because the steady-state goal is automated
  reconciliation once the source path is proven.

## Decision: No Operator Environment Variables For Desired State

Committed HCL and repository data define non-secret desired-state inputs. Local
operator workflows may rely on standard authenticated tool context, but must not
use `get_env`, `TF_VAR_*`, shell-exported values, or process environment lookups
as the durable desired-state interface.

**Rationale**: The constitution explicitly reserves environment variables for
CI/CD credential or secret injection. The bootstrap path must be repeatable and
visible in code.

**Alternatives considered**:

- Use `KUBE_CONFIG_PATH`, `KUBE_CTX`, or `TF_VAR_*` as normal local inputs.
  Rejected because it conflicts with the project constitution.

## Decision: No Public Ingress In Initial Bootstrap

Install Argo CD with an internal ClusterIP service by default and omit public
ingress from the initial bootstrap.

**Rationale**: Public HTTP entry points must be intentional, reviewed, and
documented. Argo CD can be verified through Kubernetes API access during the
bootstrap phase without exposing it publicly.

**Alternatives considered**:

- Add ingress immediately. Deferred until there is a separate explicit ingress,
  TLS, authentication, and exposure decision.
