<!--
Sync Impact Report
Version change: 1.0.0 -> 1.1.0
Modified principles:
- II. OpenTofu and Terragrunt by Default (explicit committed-input rule added)
- IV. Secret Safety and Production Guardrails -> IV. Secret Safety and CI/CD Secret Injection
Added sections:
- None
Removed sections:
- None
Templates requiring updates:
- ✅ updated: .specify/templates/plan-template.md
- ✅ updated: .specify/templates/spec-template.md
- ✅ updated: .specify/templates/tasks-template.md
- ✅ updated: AGENTS.md
- ✅ updated: ONBOARDING.md
- ✅ updated: IaC/root.hcl
- ✅ not present: .specify/templates/commands/*.md
Follow-up TODOs:
- None
-->
# Homelab Constitution

## Core Principles

### I. Repository Source of Truth

Every persistent change to the homelab MUST be represented as code in this
repository before rollout. Infrastructure, Talos machine config, Kubernetes
resources, Helm values, Argo CD desired state, scripts, and operational
documentation are the durable record. Live commands MAY inspect state or apply
repo-authored configuration, but they MUST NOT become the source of lasting
configuration.

Rationale: the homelab is both production infrastructure and a teaching
artifact. Reviewable code is the only reliable way to rebuild, audit, explain,
and recover it.

### II. OpenTofu and Terragrunt by Default

External infrastructure and infrastructure-as-code stacks MUST use OpenTofu
modules orchestrated by Terragrunt. Terragrunt MUST be the documented operator
entry point, and a clean checkout with documented credentials and deliberately
external secret material MUST be able to stand up the project from scratch with
one documented `terragrunt apply` command.

Modules MUST expose short, typed configuration surfaces instead of copy-pasted
resource blocks. Repeated infrastructure patterns MUST move behind reusable
modules or Terragrunt includes before additional instances are added.
Operator-selected inputs MUST live in committed Terragrunt/OpenTofu code,
checked-in non-secret configuration, or documented repository data files.
Environment variables MUST NOT be used as infrastructure inputs outside CI/CD
pipeline wiring.

Rationale: Terragrunt gives the project one repeatable apply surface, while
OpenTofu modules keep infrastructure understandable and rebuildable.

### III. GitOps Kubernetes Delivery

Kubernetes applications, cluster add-ons, ingress, storage classes, controllers,
and namespace-scoped configuration MUST be delivered through Argo CD, Helm,
Kustomize, raw manifests, or another declared GitOps-compatible code path in
this repository. Helm charts and values MUST render deterministically. Argo CD
Application and ApplicationSet desired state MUST be tracked in git when Argo CD
owns a workload.

Direct `kubectl edit`, `kubectl patch`, dashboard changes, or one-off live
resource mutations are break-glass actions only. Any emergency live change MUST
be backfilled into repository code before it is considered complete.

Rationale: Kubernetes behavior must be reviewable before rollout and convergent
after rollout.

### IV. Secret Safety and CI/CD Secret Injection

Secrets, kubeconfigs with private credentials, Talos secrets, age keys, tokens,
private SSH keys, private hostnames not intended for public disclosure, and raw
certificate material MUST NOT be committed. Public code MAY contain secret
references, encrypted or sealed secret manifests, ExternalSecret names, and
non-secret defaults when they are safe for a public repository.

Environment variables MUST NOT be used as general-purpose inputs for local
operator workflows, Terragrunt stacks, OpenTofu modules, Helm values,
Kustomize overlays, Talos config, or application configuration. Environment
variables MAY be used by CI/CD pipelines only as execution plumbing for
credentials, provider authentication, or secret injection. When a secret is
required, the CI/CD pipeline MUST inject it into the tool, controller, or
external secret system that needs it; the repository MUST retain only the
safe reference, template, encrypted value, or documented contract.

Live Talos and Kubernetes operations MUST be treated as production changes.
Validation appropriate to the change, such as `talosctl validate`, OpenTofu or
Terragrunt planning, Helm rendering, Kustomize builds, server-side dry runs, or
`kubectl diff`, MUST pass before live mutation unless the exception and risk are
recorded.

Rationale: a public homelab repository must be safe to inspect while still
providing enough information to operate real infrastructure.

### V. Modular, Teachable, Rebuildable Design

Code MUST be templatized and modular so common changes are made by editing short
lists of configuration options. Architecture, bootstrap, upgrade, backup,
restore, rollback, and validation decisions MUST be documented near the code
that implements them. Homelab-specific values MUST be clearly separated from
copyable teaching examples.

Stateful workloads MUST document persistent storage, backup, restore, and
failure-mode implications before rollout. New operational patterns MUST explain
why the pattern was chosen and how an operator verifies it.

Rationale: the repository is intended for future operators and readers, not just
the person who last changed it.

## Infrastructure Constraints

OpenTofu and Terragrunt are the default tools for infrastructure as code.
Terragrunt roots, includes, dependency wiring, generated provider/backend
configuration, and module inputs MUST be committed and documented well enough
for a new operator to run the declared apply path from a clean checkout.

Configuration inputs MUST be explicit in repository-owned code or data. The
project MUST NOT use `get_env`, `TF_VAR_*`, shell-exported values, or process
environment lookups to change desired state during normal operator workflows.
CI/CD MAY set environment variables only for credentials and secret injection,
and those values MUST NOT become the durable desired-state interface.

The intended steady-state bootstrap path is one documented `terragrunt apply`
command for the full project after public prerequisites, provider credentials,
and intentionally external secret material are available. Any temporary staged
bootstrap sequence MUST document why it exists, the expected follow-up that
restores the one-command path, and the validation that proves convergence.

Talos machine configuration MUST stay patch-oriented when nodes differ only by
node-specific values. Kubernetes ingress MUST be explicit and documented.
Nomad, Ansible, or host-bootstrap assumptions MUST NOT be added unless the
constitution and learner-facing documentation are amended to explain the
architecture change.

## Change Workflow and Review

Feature specs and implementation plans MUST identify the repo-owned delivery
mechanism for each persistent change: Terragrunt/OpenTofu, Argo CD, Helm,
Kustomize, raw manifests, Talos config, or a documented script that applies
repo-authored state. Plans that depend on live cluster reality MUST start with
read-only inspection.

Before implementation, the Constitution Check MUST confirm source-of-truth,
Terragrunt/OpenTofu applicability, GitOps delivery, secret safety, modularity,
committed input sources, CI/CD-only secret injection, validation, and rollback
documentation. After design, the same check MUST be re-run against the
concrete file paths and commands chosen by the plan.

Pull requests are the normal unit of change. Reviews MUST verify that permanent
behavior is captured in code, relevant docs are updated, validation output is
recorded, and any operational risk or exception is explicit.

## Governance

This constitution supersedes conflicting repository practices, templates, and
agent guidance. If another document conflicts with this constitution, the
constitution controls and the conflicting document MUST be updated in the same
change or tracked as an explicit follow-up.

Amendments MUST be made by pull request and include a Sync Impact Report that
lists changed principles, added or removed sections, templates reviewed, runtime
guidance reviewed, deferred TODOs, and the selected semantic version bump.

Versioning follows semantic versioning:

- MAJOR: backward-incompatible governance changes, principle removals, or
  redefinitions of the source-of-truth, IaC, GitOps, or safety contracts.
- MINOR: new principles, new required sections, or materially expanded guidance.
- PATCH: clarifications, wording fixes, and non-semantic refinements.

Compliance review is required for every feature plan and pull request. A change
that violates a MUST-level rule cannot proceed until the plan is changed, the
constitution is amended, or a documented break-glass exception is approved and
backfilled into code.

**Version**: 1.1.0 | **Ratified**: 2026-05-24 | **Last Amended**: 2026-05-24
