# Feature Specification: Centralize State Encryption

**Feature Branch**: `migrate-opentofu-encryption`

**Created**: 2026-11-17

**Status**: Clarified

**Tracking**: [Notion work item](https://app.notion.com/p/41ce535fc6288118a146d5f1e53314b7)

**Input**: User description: "Opentofu encryption settings need to be migrated away from the modules and to the terragrunt root.hcl file in the backend config."

## Clarifications

### Session 2026-11-17

The following are agent-resolved decisions from source evidence, not additional user statements. No user questions were needed.

- Scope: the homelab checkout and root-including unit/deletion paths are included. The separate github-iac checkout contains no matching client-encryption declarations and is excluded.
- Compatibility: preserve the metadata identity used by existing encrypted state and saved plans, in addition to the key itself. A different generated provider name cannot silently change that identity.
- Input ownership: retain resource-facing runtime-key inputs in aws-ssm-parameters and aws-github-actions-role-policy; remove only policy-exclusive module/shared inputs.
- Retirement: deletion planning currently synthesizes its own policy. It must follow the shared root policy after centralization and its focused regression must verify the resulting protection.
- Adoption: newly protected units may expose previously unencrypted records. Fail closed and report such cases; this task does not authorize plaintext fallback, live state rewriting or key rotation.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Preserve encrypted infrastructure records (Priority: P1)

As the homelab operator, I can continue reading existing encrypted state and saved plans after moving the shared policy, without rotating keys or migrating stored records.

**Why this priority**: Losing access to existing records would prevent safe infrastructure management.

**Independent Test**: Verify an encrypted pre-change fixture can be read with the generated post-change policy and confirm state and saved plans remain encrypted and enforced.

**Acceptance Scenarios**:

1. **Given** records encrypted using the existing policy, **When** the centralized policy is used, **Then** those records remain readable with the same authorized key access.
2. **Given** a normal homelab unit, **When** state or a saved plan is written, **Then** encryption remains mandatory for both.
3. **Given** missing key access or an unencrypted input, **When** a protected operation is attempted, **Then** it fails without falling back to unencrypted records.

### User Story 2 - Maintain one shared encryption policy (Priority: P2)

As a maintainer, I configure state and plan encryption once in the shared Terragrunt backend configuration, so existing and newly included modules receive a consistent policy without copying encryption settings.

**Why this priority**: Repeated module policy can drift and makes reusable modules depend on homelab state-management choices.

**Independent Test**: Inspect generated configuration for representative previously protected and previously unprotected units and verify reusable modules contain no state/plan encryption declarations or encryption-only inputs.

**Acceptance Scenarios**:

1. **Given** an existing module with a repeated policy, **When** configured through the shared root, **Then** its effective policy comes from the shared backend configuration alone.
2. **Given** a module without a repeated policy, **When** configured through the shared root, **Then** it receives the same mandatory state and plan protection.
3. **Given** an input also used for a resource, **When** encryption-only module inputs are removed, **Then** the resource retains its required input and behavior.

### Edge Cases

- Generated provider naming must retain compatibility with metadata written by the previous policy.
- An existing generated backend file must update safely without creating duplicate encryption declarations.
- Backend paths, bucket encryption, region, locking, runtime secret keys and resource identities must remain unchanged.
- Standalone module validation must work without homelab encryption-only variables.
- Retired-unit deletion planning must receive the same compatible protection after module-level policy is removed.
- Credentials may prevent authenticated planning; record this limit instead of claiming live compatibility was tested.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The shared Terragrunt root backend configuration MUST own the state and saved-plan encryption policy for all units including that root.
- **FR-002**: The migration MUST preserve existing key identity, key region, encryption strength and persisted key-provider metadata identity so previously encrypted records remain readable without rewriting them.
- **FR-003**: State and saved-plan encryption MUST both remain enforced; no plaintext fallback may be introduced.
- **FR-004**: Reusable modules MUST no longer declare state/plan encryption or accept inputs used solely for that policy.
- **FR-005**: Inputs required by actual resources MUST remain available, even if they share names with former encryption inputs.
- **FR-006**: Backend locations, locking, bucket encryption, runtime secret protection and managed resource identities MUST remain unchanged.
- **FR-007**: Focused verification MUST cover generated configuration, old-record compatibility, and enforcement; formatting and affected repository checks MUST pass or have a precise recorded blocker.
- **FR-009**: Retired-unit deletion planning MUST retain compatible mandatory state and saved-plan protection through the shared policy, including its generated fixture path.
- **FR-008**: Source-linked documentation MUST explain centralized ownership, compatibility preservation, validation and rollback without exposing secrets.

### Key Entities

- **Shared encryption policy**: The mandatory protection and key reference applied to each unit's state and saved plans.
- **Encrypted infrastructure record**: Existing or new state/saved-plan data whose readability depends on key access and compatible encryption metadata.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: One shared policy supplies mandatory state and saved-plan protection to 100% of units using the shared root.
- **SC-002**: All previously protected modules lose duplicate policy and encryption-only inputs, with zero changes to resource-facing key inputs.
- **SC-003**: Compatibility checks demonstrate that a pre-change encrypted fixture remains readable after the migration, with zero key rotation or record rewrite required.
- **SC-004**: Verification records show zero changes to backend identities and zero plaintext fallbacks.

## Assumptions

- Scope is the homelab repository's shared root and its catalog; the separate github-iac checkout is outside this task.
- Existing encryption credentials and key permissions remain available through their established paths; this change does not grant additional access.
- Units previously lacking module-level encryption should inherit the shared policy, as the user requested root ownership.
- Existing unencrypted live records, if any, are not silently adopted: inspection/planning must surface that case before application.
- This is a source refactor; live apply, key rotation and state rewriting are not part of implementation validation.
