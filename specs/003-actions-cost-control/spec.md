# Feature Specification: Homelab Actions Cost Control

**Feature Branch**: `codex/local-fix-1266`  
**Created**: 2026-10-11  
**Status**: Planned  
**Input**: Keep useful automation when changes reach `main`, allow deliberate manual runs, remove unnecessary costly pull-request and scheduled runs, and stop requiring a human reviewer for the homelab Terragrunt Plan environment.

## User Scenarios & Testing

### User Story 1 - Work continues without an environment review stop (Priority: P1)

An approved contributor can get a trusted homelab Terragrunt Plan result without waiting for the user's environment approval while existing credential and branch boundaries remain enforced.

**Independent Test**: A same-repository infrastructure PR whose live-plan scope is true reaches a terminal `Terragrunt Gate` result without a `Waiting` environment review state.

**Acceptance Scenarios**:

1. **Given** a trusted same-repository PR changing live plan inputs, **when** its required checks run, **then** `homelab-plan` does not ask for a reviewer and the plan result reaches `Terragrunt Gate`.
2. **Given** a fork PR, **when** checks run, **then** it receives no plan environment credentials and still gets the unprivileged required gate.

### User Story 2 - Routine changes avoid optional Actions runs (Priority: P2)

The user can land changes on `main` and deliberately dispatch maintenance workflows without optional PR or frequent schedule runs consuming Actions minutes.

**Independent Test**: The trigger inventory shows required PR checks remain automatic; selected optional workflows run on `main` pushes or manual dispatch as appropriate; removed schedules do not run.

**Acceptance Scenarios**:

1. **Given** a new PR, **when** Actions is evaluated, **then** all required status contexts are produced and optional image, OpenClaw, and NOFX jobs do not start solely because the PR opened.
2. **Given** a matching change lands on `main`, **when** Actions is evaluated, **then** its retained main-push workflow runs.
3. **Given** an operator dispatches an eligible workflow, **when** its input and branch guards pass, **then** the intended manual work runs under existing permissions.

### Edge Cases

- A required check is removed or renamed: reconcile the exact ruleset context and workflow change together before landing, so merges do not remain pending.
- A workflow has a path filter: do not make that context required for PRs on unrelated paths.
- `image-automation` currently observes state every five minutes; removing its schedule also removes that observation until a replacement or deliberate manual operation is established.
- A production environment reviewer may still stop unrelated production jobs; this feature changes only the `homelab-plan` reviewer requirement.

## Requirements

### Functional Requirements

- **FR-001**: The `homelab-plan` environment MUST not require a human reviewer for trusted plan jobs.
- **FR-002**: Required PR contexts in the active `main` ruleset MUST continue to be emitted automatically for every applicable PR, or the ruleset and workflows MUST change in one coordinated rollout that leaves no permanently pending checks.
- **FR-003**: Existing `main` push automation and guarded manual dispatch MUST remain available for work that still needs it.
- **FR-004**: Optional PR triggers and unnecessary schedule triggers MUST be removed or reduced only after their downstream consumers and security value are identified.
- **FR-005**: Fork, credential, OIDC, job permission, branch, concurrency, and publication gates MUST retain their existing boundaries.
- **FR-006**: The plan environment configuration, workflow trigger definitions, and operator documentation MUST agree on the intended behavior.
- **FR-007**: A read-only, SHA-bound headless diagnostic path MUST remain available for reporting live health without exposing private output.

### Key Entities

- **Workflow trigger**: Event and branch/path filter that starts a GitHub Actions workflow.
- **Required context**: Exact status name and app association enforced by the active `main` ruleset.
- **GitHub environment**: `homelab-plan` carries credentials and reviewer rules; `homelab-production` is a separate boundary.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A trusted plan enters execution without a `Waiting for review` state and ends with a terminal `Terragrunt Gate` result.
- **SC-002**: Every required PR context appears on a representative PR after the change; none remains pending because its trigger was removed.
- **SC-003**: Matching `main` pushes and intentional dispatches still produce their expected jobs.
- **SC-004**: No five-minute image automation schedule run occurs after the schedule is removed, with its loss of automatic observation documented.
- **SC-005**: Fork PRs still receive zero plan environment credentials.

## Assumptions

- The user authorizes removal of the `homelab-plan` required reviewer, not other environment or branch protections.
- Existing required PR checks have more value than their Actions cost, so they remain automatic unless the ruleset is explicitly reconciled.
- `Stuhlmuller/github-iac` is the desired-state owner for GitHub environments and rulesets; this feature may require coordinated changes across that repository and homelab.
- Production applies remain manual and exact-main-SHA guarded.
