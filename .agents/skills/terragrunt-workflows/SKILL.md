---
name: terragrunt-workflows
description: Add, refactor, validate, or troubleshoot this homelab's explicit Terragrunt stack, shared unit templates, and OpenTofu modules. Use for generated unit inputs, dependencies, state-path preservation, or Terragrunt plan/apply scope.
---

# Terragrunt Workflows

Read [GitOps ownership](../../../docs/knowledge-base/architecture/gitops-flow.md)
and only the affected source before editing. Ordinary app onboarding also uses
[the focused app skill](../homelab-app-onboarding/SKILL.md).

## Source ownership

| Concern | Edit |
| --- | --- |
| Unit identity, template source and output paths | `IaC/terragrunt.stack.hcl` |
| Per-application inputs and chart pins | `IaC/stacks/<app>/stack.hcl` |
| Shared Application defaults | `IaC/stack-defaults.hcl` |
| Reusable generated unit behavior | `IaC/.catalog/units/` |
| Backend, state encryption and shared inputs | `IaC/root.hcl` |
| Kubernetes provider connection | `IaC/kubernetes-provider.hcl` |
| Typed infrastructure resources | `IaC/modules/` or pinned catalog modules |

`IaC/bootstrap` and `IaC/live` are generated at their historical paths using
`no_dot_terragrunt_stack = true`; do not edit their generated `terragrunt.hcl`
or `terragrunt.values.hcl`. Keep unit labels, literal `source`/`path` fields,
and path identity stable: backend keys and CI's retirement parser depend on
them. OpenTofu initialization generates local `.terraform.lock.hcl` files;
they are ignored. Do not commit or copy provider locks. Exact provider versions
live in module/template HCL; CI regenerates locks and checksums during init.
`IaC/operator` remains administrator-owned rather than part of workload CI.

## Shared Application contract

All active app and platform registrations use
`IaC/.catalog/units/live/argocd-app`. Each app's `stack.hcl` loads shared locals
from `IaC/stack-defaults.hcl` and sets `inputs.defaults = local.shared.argocd_defaults`;
add only differing `metadata`, `spec` and `dependencies` fields. The root index
loads the app file's `inputs` with `read_terragrunt_config` as the unit's `values`.
Keep app filenames as `stack.hcl`, not nested `terragrunt.stack.hcl` files.
Do not duplicate the whole Application manifest.

The template derives the Application name and destination namespace from the
unit directory. Default source is `clusters/homelab/apps/<name>` at this
repository's `main`; override `spec.sources` for platform paths, Helm charts,
or multiple sources. Ordinary namespace-scoped workloads should select
`homelab-workloads` where its AppProject permissions cover their resources.

`metadata.labels`, `spec.destination`, and the nested `syncPolicy` maps merge
with defaults. Lists such as `sources`, `syncOptions`, `info` and
`ignoreDifferences` replace in full; they are not concatenated. Inspect the
rendered manifest when overriding them. Omit empty `kustomize = {}`: Argo CD
normalizes it away and leaves the declared Application OutOfSync.

Use the app file's `inputs.dependencies` for registration ordering: sibling app names or an
explicit relative unit reference, matching existing entries. A `dependency`
block is needed only when consuming outputs. Registration order does not prove
runtime readiness. Remove unused registrations from the explicit stack after
verifying their resources are absent or safe to delete. The protected workflow
discovers removed units and checks their saved destroy plans before applying.

## Generate and validate

From the repo root:

```sh
nix develop --command terragrunt hcl fmt --check
nix develop --command terragrunt --working-dir IaC stack generate
nix develop --command terragrunt hcl validate
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/conftest-policies.sh
git diff --check
```

For one generated Application, inspect only its useful rendered inputs:

```sh
nix develop --command terragrunt --working-dir IaC/live/argocd-apps/<app> \
  render --json --write=false | jq '{
    application: .inputs.manifest.metadata.name,
    namespace: .inputs.manifest.spec.destination.namespace,
    project: .inputs.manifest.spec.project,
    sources: .inputs.manifest.spec.sources,
    dependencies: .dependencies.paths
  }'
```

Backend-free unit validation requires `init -backend=false`
followed by `run --no-auto-init -- validate`; otherwise Terragrunt may initialize
the real backend. Before a real authenticated plan, reinitialize the intended
backend. Use [validation gates](../../../docs/knowledge-base/operations/validation-gates.md)
for the exact unit commands and known live prerequisites.

Use `scripts/ci/terragrunt-plan.sh` for the reviewed PR planning scope; inspect
its exclusions before interpreting a successful result. It intentionally omits
secret-bearing units. Pure refactors must preserve rendered manifests, unit
identities, dependency order and backend keys; inspect the affected real plan
when credentials are available and record an unavailable plan explicitly.

Apply through the [declared workflow](../../../docs/ci-cd.md), within existing
user authorization, after relevant validation. Do not substitute a blanket
`stack run apply` for the repository's staged, policy-checked saved-plan path.
Keep remote module sources immutable, desired state in committed non-secret
inputs, and provider generation scoped to units that need it. Update the
affected knowledge-base notes in the same change.
