# Implementation Plan: Bootstrap Argo CD With Terragrunt

**Branch**: `001-bootstrap-argocd-terragrunt` | **Date**: 2026-05-24 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-bootstrap-argocd-terragrunt/spec.md`

## Summary

Bootstrap Argo CD through a repository-owned Terragrunt apply path, then hand
steady-state Argo CD configuration to Argo CD itself. The implementation will
source the catalog-backed Helm release module directly from
`terragrunt-catalog` version `0.3.0` and expose one Terragrunt entry point that
installs Argo CD, waits for the Argo CD Application CRD, and applies the
self-management Application through a Terragrunt `after_hook`.

## Technical Context

**Language/Version**: HCL for Terragrunt/OpenTofu, Kubernetes manifest schemas, Markdown runbooks
**Primary Dependencies**: Terragrunt, OpenTofu, Helm provider, Kubernetes provider, Argo CD Helm chart, Argo CD Application CRD
**Storage**: S3 remote state from `IaC/root.hcl`; no workload persistent storage introduced by this feature
**Testing**: `terragrunt hcl fmt --check`, `tofu validate`, `terragrunt plan`, Helm rendering/provider plan, Kubernetes read-only verification
**Target Platform**: Talos-backed Kubernetes homelab cluster with Argo CD installed into the `argocd` namespace
**Project Type**: Infrastructure-as-code and GitOps bootstrap
**Infrastructure Entry Point**: `IaC/bootstrap/argocd/terragrunt.hcl`
**Delivery Mechanism**: Terragrunt/OpenTofu seed path followed by Argo CD steady-state reconciliation
**Secrets Model**: No committed secrets; provider credentials and any repository credentials are external secret material or CI/CD-injected credentials only
**Input Model**: Committed non-secret Terragrunt/OpenTofu inputs; no operator environment variables as desired-state inputs
**Performance Goals**: A documented bootstrap workflow completes the install and self-management registration in one operator workflow; Argo CD reports the application within 10 minutes after apply
**Constraints**: Argo CD CRDs must exist before the self-management Application is applied; first handoff is validated before automated prune/self-heal is enabled
**Scale/Scope**: One Argo CD installation, one self-management application, and the supporting runbook/validation path

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Repository Source of Truth**: PASS. All durable behavior will be captured in
  `IaC/bootstrap/argocd/`, Argo CD desired-state paths, and
  `ONBOARDING.md` or a dedicated runbook.
- **OpenTofu/Terragrunt**: PASS. The feature uses OpenTofu modules orchestrated
  by Terragrunt, with one documented `terragrunt apply` entry point at
  `IaC/bootstrap/argocd/terragrunt.hcl`.
- **GitOps Kubernetes Delivery**: PASS. Terragrunt is limited to initial
  bootstrap. Argo CD owns steady-state Argo CD configuration after handoff.
- **Secret Safety**: PASS. The plan introduces no raw secrets. Repository or
  provider credentials remain external or CI/CD-injected.
- **Input and Secret Injection**: PASS. Desired-state inputs are committed as
  non-secret HCL/map values; no `get_env`, `TF_VAR_*`, or shell-exported
  desired-state inputs are allowed.
- **Modularity**: PASS. The bootstrap stack sources the catalog
  `helm-release` module directly at version `0.3.0` and keeps repo inputs
  short and explicit.
- **Validation**: PASS. The plan names formatting, validation, planning, and
  read-only Kubernetes checks before live rollout.
- **Operations Documentation**: PASS. Quickstart/runbook covers prerequisites,
  apply, verification, rollback, and partial-bootstrap recovery.

**Post-Design Re-check**: PASS. Phase 1 artifacts preserve the same ownership
boundary: Terragrunt seeds Argo CD once, Argo CD owns steady-state configuration,
and all operator inputs are committed non-secret configuration or external
credential material.

## Project Structure

### Documentation (this feature)

```text
specs/001-bootstrap-argocd-terragrunt/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── bootstrap-operator-contract.md
└── checklists/
    ├── bootstrap.md
    └── requirements.md
```

### Repository Paths (repository root)

```text
IaC/
├── root.hcl
├── bootstrap/
│   └── argocd/
│       └── terragrunt.hcl

clusters/
└── homelab/
    └── argocd/
        └── self-management/

ONBOARDING.md or docs/argocd-bootstrap.md
```

**Structure Decision**: Use `IaC/bootstrap/argocd/terragrunt.hcl` as the single
operator entry point. Source
`git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/helm-release?ref=0.3.0`
directly and use a Terragrunt `after_hook` to wait for
`applications.argoproj.io` before applying the self-management Application
manifest. This avoids the Helm CRD discovery race on a clean cluster without
repository-local OpenTofu modules. Store Argo CD steady-state desired state
under a cluster-scoped GitOps path.

## Complexity Tracking

No constitution violations or complexity exceptions are required.
