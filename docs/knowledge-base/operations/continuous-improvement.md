# Continuous Improvement

Tags: #operations #security #reliability #stewardship

Source: `AGENTS.md`

This homelab should improve continuously through small, reviewable changes.
Agents should treat it as home turf: notice weak assumptions, hardening
opportunities, reliability gaps, missing validation, and operational friction
before they become incidents.

## Stewardship Loop

1. Start from source-backed context: relevant code, runbooks, knowledge-base
   notes, and read-only live inspection when the question depends on current
   cluster reality.
2. Prefer repo-owned desired state over manual repair. Express fixes in
   Terragrunt, OpenTofu, Helm values, Kustomize/manifests, scripts, or docs
   before any rollout.
3. Keep improvements small enough to review. Security and reliability work is
   better as a steady stream of scoped PRs than a rare sweeping rewrite.
4. Validate with the smallest gate that proves the change, then record any
   unavailable validation plainly.
5. Update this vault whenever a finding, decision, source path, risk, or
   follow-up matters beyond the current chat.

## Finding Format

Record findings in the most specific affected note when one exists. Use this
page for cross-cutting or not-yet-owned findings.

- **Status:** open, planned, fixed, accepted risk, or obsolete.
- **Area:** workload, platform service, Talos, networking, storage, CI/CD,
  secrets, observability, or agent runtime.
- **Evidence:** source path, command, PR, or read-only observation.
- **Risk:** what could fail, leak, drift, or become hard to operate.
- **Next step:** concrete repo-owned action or validation gate.

## Current Standing Order

Rodman asked Claw to continue making security and reliability improvements as
needed, to treat the homelab as home, and to mark findings in
`docs/knowledge-base/`. This page is the durable capture point for that work
when a more specific note does not already own the finding.

## Open Findings

- **Status:** open
- **Area:** agent runtime
- **Evidence:** OpenClaw pod currently runs on an NFS-backed PVC where files can
  appear as `nobody:nogroup`; PR #296 configures workspace scratch paths and
  Git safe-directory state in pod bootstrap.
- **Risk:** future agent work can hit Git ownership checks or brittle cleanup
  paths if runtime setup drifts from the PVC ownership model.
- **Next step:** after PR #296 syncs, verify the rolled pod has
  `GIT_CONFIG_GLOBAL=/data/openclaw/gitconfig`, can run `git status` in
  `/data/openclaw/workspace`, and has
  `/data/openclaw/workspace/.openclaw/trash`.
