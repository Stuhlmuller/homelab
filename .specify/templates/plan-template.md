# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]
**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]
**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]
**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]
**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]
**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]
**Project Type**: [e.g., library/cli/web-service/mobile-app/compiler/desktop-app or NEEDS CLARIFICATION]
**Infrastructure Entry Point**: [Terragrunt stack/path, Argo CD app path, Helm chart, Kustomize overlay, Talos config, or N/A]
**Delivery Mechanism**: [Terragrunt/OpenTofu, Argo CD, Helm, Kustomize, raw manifests, Talos config, or NEEDS CLARIFICATION]
**Secrets Model**: [ExternalSecret/SOPS/sealed secret/reference-only/no secrets, or NEEDS CLARIFICATION]
**Input Model**: [Committed non-secret config/data files; CI/CD-injected secrets only; no operator environment variables, or NEEDS CLARIFICATION]
**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]
**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]
**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Repository Source of Truth**: All persistent changes are captured in this
  repository before rollout; live commands are read-only or apply repo-authored
  state.
- **OpenTofu/Terragrunt**: External infrastructure changes use OpenTofu modules
  orchestrated by Terragrunt, with a documented apply path that preserves the
  one-command-from-scratch target.
- **GitOps Kubernetes Delivery**: Kubernetes changes use Argo CD, Helm,
  Kustomize, raw manifests, or another declared repo-owned GitOps path.
- **Secret Safety**: No raw secrets, private credentials, Talos secrets,
  kubeconfigs, tokens, or certificate material are introduced.
- **Input and Secret Injection**: Desired-state inputs are committed as
  non-secret code or data; environment variables are used only by CI/CD for
  credentials or secret injection, never as normal operator inputs.
- **Modularity**: Repeated patterns are templatized behind modules, includes,
  values, overlays, or short configuration lists.
- **Validation**: The plan names the relevant validation commands, such as
  Terragrunt/OpenTofu plan, Helm rendering, Kustomize build, server-side dry
  run, `kubectl diff`, or `talosctl validate`.
- **Operations Documentation**: Architecture decisions, verification, rollback,
  storage, backup, restore, and failure modes are documented where applicable.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Repository Paths (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# Replace with the concrete paths touched by this feature and remove unused
# examples before finalizing the plan.
.talos/                         # Talos configs, patches, and generated-safe references
IaC/root.hcl or IaC/**/terragrunt.hcl
modules/**                      # OpenTofu modules when reusable infrastructure is added
clusters/**                     # Cluster-level GitOps resources
apps/**                         # Application manifests, values, or overlays
charts/**                       # Helm charts owned by this repository
docs/ or ONBOARDING.md          # Learner-facing docs and runbooks
scripts/                        # Repeatable operator commands and validation helpers
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
