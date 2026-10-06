---
type: runbook
title: "CI/CD"
description: "Trusted Terragrunt plan and exact-SHA apply workflows, Policy Bot merge rules, environment approvals, and credential recovery."
tags: ["runbook", "ci", "github-actions"]
---

# CI/CD

Canonical runbook: [`docs/ci-cd.md`](../../docs/ci-cd.md)

Pull requests always emit the aggregate `Terragrunt Gate`; only trusted changes
to live inputs enter the protected plan environment. Pushes to `main` emit an
exact-SHA apply request, and an operator dispatches the protected apply. AWS,
Azure, Kubernetes, and Octelium credentials remain GitHub environment inputs,
while desired state stays in repository-owned files.

Policy Bot automatically approves PRs through `requires.count: 0` in
[`.policy.yml`](../../.policy.yml); human and Codex reviews are optional.
Required GitHub checks and explicit Stuhlmuller organization-member disapproval
still block merges. The policy takes effect from the target branch after merge;
revert `.policy.yml` to restore review requirements.

Read-only GitHub inspection on 2026-10-06 UTC confirmed that `main` ruleset
`14700233` already requires zero approving reviews. The `homelab-plan` and
`homelab-production` environments separately require `rstuhlmuller` approval,
despite the canonical runbook describing production as having no reviewer.
Policy changes do not remove those environment gates. Reconcile the environment
configuration and runbook through the repository workflow before treating
Terragrunt plans or applies as unattended.

See [Validation Gates](../operations/validation-gates.md) and [GitOps Flow](../architecture/gitops-flow.md).

## Credential recovery: 2026-09-26

Protected plan
[35564778374](https://github.com/Stuhlmuller/homelab/actions/runs/35564778374)
failed after static checks. Both CI secrets were last updated August 26,
matching the documented 30-day credential lifetime. The pinned operator CLI's
callback login failed on the public path, then succeeded with the same client
and temporary home through the existing TLS-preserving `native_transport` in
`scripts/octelium-nofx-reconcile.py`.

The existing credential helper passed Bash, ShellCheck, and dry-run checks,
then rotated the `homelab-plan` and `homelab-production` environment secrets
at 18:19:53 and 18:19:54 UTC. Protected read-only
[diagnostics 36262232916](https://github.com/Stuhlmuller/homelab/actions/runs/36262232916)
at main `c3181b5adf867ae52c8f80733f7bf3fed67d89eb` passed authenticated
Kubernetes API and Grafana readiness checks. Operator logout succeeded and
the temporary home and transport were removed. No production apply ran.

Follow the [canonical rotation procedure](../../docs/ci-cd.md); the next 21-day
rotation is due October 17, 2026. Do not infer rollout completion from
credential recovery or read-only diagnostics.
