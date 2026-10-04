---
name: homelab-protected-prs
description: Complete authorized homelab pull-request repair and protected merges, including all-PR sweeps, without bypassing checks or approval rules. Use when asked to fix and merge PRs or diagnose merge protection.
---

# Homelab Protected PRs

Read [the approval policy](../../../.policy.yml),
[review instructions](../../../AGENTS.md) and the
[CI security model](../../../docs/ci-cd.md#security-model). Inspect GitHub's
current rules and checks; historical check lists are not current evidence.
This skill does not grant permission to post comments/reviews or merge; use
the user's existing requested scope.

1. Inventory the requested PRs with `gh pr list` / `gh pr view`; for an all-PR
   sweep, preserve the complete set and refresh it before declaring completion.
   Record each head SHA, base branch, draft state, checks, review threads,
   approval evidence and mergeability.
2. Repair actual failures in isolated branches/worktrees. Run the affected
   local gates; wait for checks on the new exact head. Do not treat a prior
   green commit or an aggregate status alone as proof of current approval.
3. Verify every PR-introduced commit's GitHub signature status. A verified tip
   does not repair an unsigned ancestor. If authorized history repair is
   needed, preserve a backup ref and exact tree, use an explicit expected-head
   force-with-lease, then obtain fresh checks and approval.
4. Require an accepted `.policy.yml` approval path, current required checks,
   and resolved addressed review threads. Chat consent is not a GitHub policy
   signal. Only when acting as the Codex review bot after a passing review with
   no P0/P1 alerts, add the exact top-level `👍` required by `AGENTS.md`; do not
   impersonate that bot or manufacture approval with another account.
5. Re-read head/base immediately before the authorized squash merge. Use the
   normal protected merge path; do not use admin bypass or relax rules.
   A later push invalidates approval, so restart the affected checks if head
   changes. An auto-merge request is pending work, not a merged PR.
6. Verify GitHub reports the PR merged, inspect the merge commit's verified
   signature and sole parent, and confirm it is reachable from current `main`.
   Check the resulting tree for the intended changes. For a sweep, account for
   every original and newly relevant PR explicitly.

When approval or an external check is unavailable, report that exact pending
gate; continue independent repairs. Merge completion is separate from
[deployment and live acceptance](../homelab-release-verification/SKILL.md).
