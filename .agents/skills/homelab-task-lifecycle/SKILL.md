---
name: homelab-task-lifecycle
description: Scope and resume an authorized homelab task from issue through protected delivery and functional acceptance, preserving ownership and evidence across sessions.
---

# Homelab Task Lifecycle

Use for multistage repository or runtime work and interrupted handoffs. Inputs:
the user's request/authority, existing issue or spec, and affected resources.
Read [the lifecycle runbook](../../../docs/autonomous-task-lifecycle.md) and the
relevant quickstart route. Reuse existing owners, PRs and automation.

1. Establish one durable issue using the task form. Record owner, scope,
   dependencies, executable acceptance, permitted actions, current stage,
   evidence, blocker and next action. Keep credentials/private receipts out of
   public records. A task record does not grant permissions.
2. Before writing, check ownership and create an isolated worktree. Use the
   existing PR-delivery atomic claim after a PR exists. Its lock spans local
   worktrees only; use one dispatcher and assigned scopes across hosts. Never
   take over an active owner or infer expiry from silence.
3. On resume, refresh source, head/checks, merge state and affected runtime.
   Inspect prior effects before repeating uncertain operations. Reuse valid
   evidence; invalidate it when its revision, configuration or state changes.
4. Implement the smallest complete change and run relevant checks. Delegate
   bounded independent research/review; retain one writer per branch/resource.
   Follow PR contribution, protected-PR and release-verification skills for
   their stages. Reuse their current authority instead of asking again.
5. Advance every successful stage to its next authorized action. Before yielding,
   persist the stage, attempts, blocker, next action, resume condition and actual
   runner. Use the runbook's 30-minute budget, three-attempt limit and backoff.
   A skill or printed dispatch command is not a continuation trigger.
6. Verify the exact deployed revision with `scripts/verify-gitops.py`, exercise
   the requested service behavior, then recheck revision. Source-only tasks
   explain why deployment is inapplicable. Close runtime issues only after
   functional acceptance; do not use premature PR auto-closing keywords.

For failed checks or rollout, retain evidence, fix the owning source or follow
the workload's tested rollback/restore path. Stop repeated no-progress attempts
and record the precise unmet prerequisite. Prepare reviewable work before an
approval request; never widen credentials, spending, exposure or policy to pass.
An unavailable cluster does not prevent source work or resumption from GitHub.

Output: linked issue/PR/check and revision-bound acceptance evidence, current
stage, remaining blocker/next action, verified continuation status, intervention
count and recovery outcomes. Mark unmeasured time/model cost as unknown. Do not
claim ongoing operation without an observed runner wakeup and durable progress.
