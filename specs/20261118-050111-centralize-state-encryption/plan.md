# Implementation Plan: Centralize State Encryption

**Branch**: `migrate-opentofu-encryption` | **Date**: 2026-11-17 | **Spec**: [spec.md](spec.md)

## Summary

Move client-side state and saved-plan encryption into `IaC/root.hcl`'s `remote_state.encryption` map. Use AWS KMS, the existing key/region/key specification, explicit enforcement and `encrypted_metadata_alias = "key_provider.aws_kms.main"` to preserve existing persisted metadata despite Terragrunt naming generated blocks `default`. Remove repeated module policy and policy-only inputs, plus the independent deletion-fixture policy. Pin only Terragrunt to released v1.2.2 because the locked package and available v1.0.8 binary cannot generate enforcement correctly.

## Technical Context

**Language/Version**: HCL, Python 3, Bash; Terragrunt v1.2.2; existing OpenTofu package retained.

**Primary Dependencies**: existing Nix flake and pinned nixpkgs; Terragrunt generation; OpenTofu AWS KMS encryption.

**Storage**: existing S3 state bucket and keys remain unchanged; offline tests use temporary local state only.

**Testing**: real Terragrunt generation, OpenTofu old/new state and saved-plan round trips with an offline PBKDF2 fixture, negative compatibility/enforcement tests, existing Python stack regressions, formatting/static/policy checks.

**Target Platform**: existing four Nix systems; validation in Linux cloud environment.

**Project Type**: internal IaC orchestration refactor.

**Performance Goals**: no added network dependency or extra encryption work beyond existing policy; no performance feature.

**Constraints**: no plaintext fallback, key rotation, live state rewrite, backend path change, generated-unit hand edits or unrelated nixpkgs upgrades. Pin reproducible tool artifacts with real hashes, never fake values.

**Scale/Scope**: eleven currently duplicated module policies, every unit including shared root, retired-unit fixture generation and focused CI/docs.

## Constitution Check

Pre-research: PASS. Repository-owned configuration, public-safe references, existing orchestration and scoped validation satisfy principles I–V. No live mutation planned.

Post-design: PASS. Explicit enforcement and metadata alias preserve protection; unchanged backend and resource inputs preserve bootstrap. Runtime secret keys remain distinct. Documentation explains compatibility and rollback; authenticated plan limits must be reported. No constitution exception.

## Project Structure

```text
IaC/root.hcl
IaC/terragrunt-catalog/modules/*/{main,versions,variables}.tf
scripts/ci/terragrunt-filter-base.sh
scripts/ci/terragrunt-stack-test.py
scripts/ci/state-encryption-test.py
scripts/ci/offline-checks.sh
flake.nix
docs/state-encryption.md
README.md
specs/20261118-050111-centralize-state-encryption/{spec,plan,research,data-model,quickstart,checkpoint}.md
```

**Structure Decision**: retain existing ownership. Do not add an external interface or contracts directory: this is internal generation behavior.

## Design

1. Supply `key_provider = "aws_kms"`, existing `kms_key_id`, `region`, `key_spec`, `encrypted_metadata_alias = "key_provider.aws_kms.main"` and `enforced = true` in the root remote-state encryption map. Do not add fallback. Preserve the existing `config` map byte-for-byte where practical.
2. Pin released Terragrunt v1.2.2 narrowly in the Nix package set used by the development shell. Package the official v1.2.2 release binaries for all four existing systems using the existing flake archive pattern. Fetch the published checksum manifest, match each platform artifact SHA256, and pin those verified hashes in the Nix derivation; validate the Nix-supplied binary in the existing shell with `--no-update-lock-file --no-write-lock-file`. This avoids importing Go 1.27.4 into the pinned toolchain, which a source build would require. Keep nixpkgs input and flake.lock unchanged. Keep all four supported systems. Assert binary version and generated output during validation. Update tool-version documentation where relevant.
3. Remove only repeated `terraform.encryption` blocks and the corresponding module variable declarations/references that are exclusive to encryption. Remove root's three shared policy-only inputs; retain its locals to feed centralized generation. Preserve runtime `kms_key_id` variables in aws-ssm-parameters and aws-github-actions-role-policy and their explicit unit overrides. Search tests/examples/docs for stale removed inputs.
4. Retired-unit generation already inherits root. Remove its synthetic encryption block entirely so backend generation supplies the one policy. Revise its regression to assert root encryption values, no duplicate block in synthesized module config, unchanged state identity and runtime-key exclusion. Test generated backend syntax as well as render JSON.
5. Add a bounded offline regression that invokes the real supported Terragrunt and OpenTofu executables. Capture actual AWS KMS backend generation from a temporary copy of the real root using a non-cloud CLI capture shim, and separately generate a local-backend PBKDF2 policy through the same real Terragrunt generator for runtime metadata compatibility checks. The PBKDF2 map is a standalone disposable analogue, not a modified production root; production settings and ownership are asserted independently. Produce old state and a saved plan under old `main` provider policy using a harmless built-in terraform_data resource, then read old state and show/apply the old plan under generated `default` policy with preserved metadata alias. Verify new state/plan remain encrypted and readable under the old-compatible policy. Negative cases remove/change the alias, supply plaintext state/plan and assert failure. PBKDF2 supplies persisted random-salt metadata, making missing alias a real decrypt failure rather than a string assertion. This checks metadata migration and plan behavior without pretending to test AWS permissions. Keep all fixture secrets/results temporary and public-safe.
6. Register the focused regression in `scripts/ci/offline-checks.sh` beside the existing stack regression; static checks consume this owner through nix-checks. Publish source-authored guidance in `docs/state-encryption.md` and link it from README. OpenWiki lifecycle tools and a readily callable CLI are unavailable here, so preserve the managed wiki/control artifacts and record that limit. This coordinator-authorized documentation path fulfills FR-008 without claiming an unperformed wiki update. Explain ownership, exact minimum/pin, metadata alias rationale, verification limitations, fail-closed legacy plaintext handling and source rollback. Distinguish previously encrypted modules from newly protected units: after a newly covered unit writes ciphertext, retain equivalent encryption during a source rollback until a separate migration is designed. No live state download.

## Verification and Rollback

Follow [quickstart](quickstart.md). Generated KMS HCL must validate without duplicate blocks; genuine KMS decrypt requires established authenticated planning and cannot be proven by PBKDF2. Compare backend render identities against pre-change fixtures. Before live encrypted writes, source and tool pin can be reverted together. After activation, the metadata alias preserves compatibility for the eleven previously protected modules. Newly protected units must retain equivalent encryption after their first ciphertext write until a separate migration is designed; removing their policy in a blanket revert would make their records unreadable. Never restore old state over current infrastructure merely to roll back source.

## Recorded Design Amendment

The implementation found no callable OpenWiki lifecycle tool/CLI. The coordinator authorized source-authored `docs/state-encryption.md` plus README instead of the planned managed wiki update. Existing managed wiki content was not edited and no lifecycle operation is claimed. This changes the documentation destination, not the FR-008 behavior or acceptance obligation. The actual declared regression owner is `scripts/ci/offline-checks.sh`, consumed by the static/Nix check path. Existing stage checkpoints retain the original decision and execution history.
