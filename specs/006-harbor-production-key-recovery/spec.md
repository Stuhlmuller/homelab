# Feature: Production-only Harbor signing recovery

Date: 2026-10-29. Status: LOCAL preparation; no publication or live execution authorized.
Reconciles the saved active feature pointer from completed DNS retirement (005).
Its spec/plan/tasks and completed migration acceptance remain unchanged.

## Stories and independent acceptance

- US1 (P1): Prepare an operator helper restricted to the existing apply key,
  generation 2, expiry 2027-01-25T02:58:13Z. Inert tests prove wrong identity,
  generation, expiry, actor, signer, CLI or provider state cannot trigger signing.
- US2 (P1): Preserve durable intent/captured output and recover interrupted
  completion without repeating signing. Inert tests prove uncertain calls never
  auto-retry; complete captures reconcile idempotently; partial/lost output stops.
- US3 (P2): Keep source preparation, source publication, signing, secret install,
  live publication and runtime/backup acceptance as distinct approval gates.
  Actual checked tasks represent only completed work, never inferred live success.

## Requirements

- FR-001: Use existing encrypted provider state, only apply, exact tag
  tag:homelab-ci-apply and valid reusable/ephemeral/preauthorized properties.
  No new raw key/provider write, plan/Cordium signing or secret operations.
- FR-002: Require clean signed current main, rstuhlmuller, approved trusted Mac
  and pinned installed operator CLI. Default preview performs no writes.
- FR-003: Execution requires exact identity/generation/expiry/signer pins and an
  explicit new-delegated-authority acknowledgement. Approval is still external.
- FR-004: Before invoking the supported stdin-only signing command, persist an
  intent and create protected stdout capture. Retain them on every uncertain exit.
- FR-005: Owned 0700 directory, 0600 regular files, no symlinks, bounded reads,
  exclusive cache lock, atomic/fsynced JSON and capture directory entries.
- FR-006: Recovery never signs. Verify exactly one added authority, no changed
  old authority metadata, provider/Mac/time binding, captured wrapper and cache
  baseline. Append only a new apply record; preserve all existing records.
- FR-007: Never erase intent to retry, reconstruct missing private material,
  retire authorities, modify ACLs/RBAC, enroll a node, publish secrets or dispatch.
- FR-008: Record the persistent delegated-authority consequence and existing
  cluster-admin plus broader TCP443 reachability. Key expiry is not authority revocation.

## Last verified live evidence; not renewed by mock tests

Generation 2 expires 2027-01-25T02:58:13Z; no matching production cache,
no pending receipt, no trusted authority metadata matching the current key in
known authorized locations. Old cached authority remains preserved.1752/1753
heads are e3a6522118b266c3796c462b610fc5a90cbf5f3c and
9bf484b63e87068f8abcc510922626cdab30f025 respectively.
