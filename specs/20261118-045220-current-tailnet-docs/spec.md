# Feature Specification: Current Tailscale Enrollment Documentation

**Feature Branch**: `docs/current-tailnet-enrollment`

**Created**: 2026-11-17

**Status**: Clarified

**Tracking**: [Documentation work item](https://app.notion.com/p/41ce535fc6288187954dfe367b1766f7?pvs=204)

**Input**: Keep Tailscale documentation focused on the current enrollment setup, with no historical or migration narrative.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Read accurate enrollment guidance (Priority: P1)

An operator reads networking, identity, CI and workload documentation and finds only prerequisites applicable to the current setup.

**Why this priority**: Accurate prerequisites let operators understand ordinary device enrollment.

**Independent Test**: Review every affected enrollment section for current authentication, tags, access policy and reachability guidance.

**Acceptance Scenarios**:

1. **Given** a device or runner enrollment, **When** an operator consults the docs, **Then** every stated prerequisite applies to the current setup.
2. **Given** a reader navigating the wiki, **When** they follow enrollment links, **Then** every destination provides current, relevant guidance.

### User Story 2 - Retain usable current documentation (Priority: P2)

A maintainer can find valid authentication, network routing, secret handling and validation guidance throughout the repository.

**Why this priority**: Editing enrollment prose must preserve independently useful instructions.

**Independent Test**: Review the complete documentation diff against owning source and check internal links and formatting.

**Acceptance Scenarios**:

1. **Given** a mixed-purpose document, **When** enrollment prose is revised, **Then** valid routing, credential safety and unrelated validation information remains coherent.
2. **Given** an operator helper, **When** its instructions are retained, **Then** the documented usage is supported by its implementation.

### Edge Cases

- Earlier specification packages and local skill prose must be consistent with current reader-facing guidance.
- Documents outside the current enrollment model must not leave dangling inbound links or historical stubs.
- Generated wiki state has separate ownership and must not be hand-edited.
- Commit verification and webhook authentication remain independent requirements.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Authored documentation MUST describe only current authentication, tags, access policy and network reachability prerequisites.
- **FR-002**: Documentation MUST read as a direct description of the current setup, without historical or migration explanations.
- **FR-003**: Every retained enrollment document and inbound link MUST serve the current setup; irrelevant dedicated documents MUST be deleted without stubs.
- **FR-004**: Independent authentication, access control, secret safety, routing, storage, commit verification and webhook authentication guidance MUST remain accurate.
- **FR-005**: Changes MUST be limited to documentation and feature records; runtime configuration, executable helpers, credentials and live infrastructure MUST remain unchanged.
- **FR-006**: Every retained operational recipe MUST be grounded in current source; unsupported replacement invocations MUST NOT be invented.
- **FR-007**: Generated wiki control state, Claims, indexes and provenance MUST remain under their established ownership.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Full review finds zero enrollment prerequisites outside the current documentation model.
- **SC-002**: All documentation links resolve to retained files and headings.
- **SC-003**: Affected documentation passes available link and formatting checks, or a precise pre-existing or tooling limitation is recorded.
- **SC-004**: The final change contains zero runtime, credential or live infrastructure mutations.

## Assumptions

- The user-provided enrollment state is authoritative for this documentation-only task.
- All repository-authored documentation is in scope, including relevant earlier specification prose and local skills.
- Executable-source discrepancies are reported separately rather than silently repaired outside documentation scope.
- Generated wiki control records are excluded from manual edits.

## Clarifications

### Session 2026-11-17

- Agent decision from explicit scope: apply the current documentation model consistently to authored specs and local skills.
- Agent decision from ownership: edit authored wiki prose while preserving generated state.
- Agent decision from source inspection: retain only supported operational recipes; preserve independent commit verification and webhook authentication.
