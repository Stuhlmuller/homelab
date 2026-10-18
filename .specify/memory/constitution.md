<!--
Sync Impact Report
- Version change: unversioned template → 1.0.0
- Modified principles: five template placeholders → five project principles below
- Added sections: Technology and Ownership; Delivery and Review Gates
- Removed sections: none; placeholder sections were filled
- Follow-up TODOs: none
-->
# Homelab Constitution

## Core Principles

### I. Repository-Owned Desired State

Infrastructure and workload changes MUST be represented in repository-owned code before
changing live state. Infrastructure MUST use OpenTofu modules orchestrated by Terragrunt;
Kubernetes workloads MUST use Argo CD, Helm, Kustomize, repository-owned manifests, or
another declared repository path. Operators MUST NOT repair drift with ad hoc live
mutations. The sole narrow manual-cloud exception is the authorized Entra conversion
defined in [AGENTS.md](../../AGENTS.md), including all of its prerequisites. This keeps
cluster state reproducible and reviewable.

### II. Public Repository and Secret Safety

Secrets, private credentials, keys, raw certificates, and sensitive kubeconfigs MUST NOT
be committed. Desired-state inputs MUST be committed as non-secret code or data, rather
than supplied through process environment variables. CI/CD MAY use environment variables
for credentials and secret injection; git MUST contain only safe references, encrypted
material, templates, or contracts. Runtime secrets SHOULD be file-backed or
controller-managed. These boundaries let a public repository remain usable without
exposing operational credentials.

### III. Validation Before Production Change

Live Talos and Kubernetes operations MUST be treated as production changes. Relevant
validation MUST pass before live changes, or its unavailability MUST be recorded. Affected
Terragrunt/OpenTofu stacks require formatting and planning; Talos configuration requires
strict validation; Kubernetes changes require an appropriate render, diff, or dry run.
Read-only inspection SHOULD precede changes to bootstrap, networking, storage, and
upgrade assumptions. Validation reduces the chance of an unsafe rollout.

### IV. Reviewable and Teachable Changes

PRs SHOULD be the normal unit of cluster change. Architecture, workflow, and operational
changes MUST explain why and include the relevant source-linked documentation. Automation
MUST document what it changes, how to verify it, and how to roll it back. Stateful workloads
MUST document storage, backup, and restore implications; public ingress MUST be explicit
and reviewed. Examples MUST distinguish public teaching values from homelab-specific or
private values. This repository is both production infrastructure and a learning resource.

### V. Reproducible Bootstrap and Clear Ownership

The steady-state bootstrap MUST preserve one documented `terragrunt apply` path after
public prerequisites and external secret material are available. Temporary staged
bootstrap MUST explain the reason and path back to a single apply. Changes MUST follow
the ownership boundaries in [AGENTS.md](../../AGENTS.md): `.talos/` for Talos,
Kubernetes app and cluster directories for runtime resources, `IaC/` for infrastructure,
`docs/` for guides, `openwiki/` for cross-cutting knowledge, and `scripts/` for operator
helpers. Clear ownership keeps setup repeatable and changes easy to locate.

## Technology and Ownership

Talos Linux, Kubernetes, OpenTofu, Terragrunt, Argo CD, Helm/Kustomize-compatible sources,
AWS SSM Parameter Store, and external-secrets form the current declared stack. New
workloads and platform dependencies MUST use the existing repository patterns or explain
a deliberate change. Nomad, Ansible, and host-bootstrap assumptions MUST NOT be
reintroduced without an intentional codebase change and documentation of its reason.
Generated OpenWiki pages MUST NOT be hand-edited; follow the repository OpenWiki policy
when cross-cutting knowledge needs updating.

## Delivery and Review Gates

Before a substantive change, inspect the relevant source and task context; inspect live
state with read-only commands when reality matters. Run the repository validation gate
when available and the narrow checks specific to the affected stack or manifests. Update
affected documentation and knowledge notes in the same PR, then re-run relevant validation.
For live rollout, complete documented cluster checks before applying through the declared
path. Report changed behavior, validation evidence, and remaining operational risk.

## Governance

Amendments MUST use the normal PR workflow, state the reason and affected rules, and keep
this constitution consistent with the detailed operational policy in
[AGENTS.md](../../AGENTS.md). Changes that affect existing deployed state MUST include
the required transition and rollback explanation. Each feature plan and change review
MUST check relevant principles; any exception MUST be justified and cannot bypass the
repository's safety rules.

Constitution versions follow semantic versioning: MAJOR for incompatible principle
removals or redefinitions, MINOR for new principles or materially expanded guidance, and
PATCH for non-semantic clarification. This first populated constitution is version 1.0.0.

**Version**: 1.0.0 | **Ratified**: 2026-10-18 | **Last Amended**: 2026-10-18
