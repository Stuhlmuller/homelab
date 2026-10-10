---
type: runbook
title: "CI/CD"
description: "Trusted Terragrunt plan and exact-SHA apply workflows, Policy Bot merge rules, environment approvals, and credential recovery."
tags: ["runbook", "ci", "github-actions"]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-10T23:09:14.896Z
sources:
  - id: openwiki-source-e0d1dba87aa9213350b1234a
    resource: repo://docs/ci-cd.md
  - id: openwiki-source-e038674a313521b0f6eadc03
    resource: repo://docs/cordium-ci.md
generated: { by: "codex", at: "2026-10-10T23:09:14.896Z" }
---

# CI/CD

Canonical runbook: [`docs/ci-cd.md`](../../docs/ci-cd.md)

Pull requests always emit the aggregate `Terragrunt Gate`; only trusted changes
to live inputs enter the protected plan environment. Pushes to `main` emit an
exact-SHA apply request, and an operator dispatches the protected apply. AWS,
Azure credentials and scoped pre-signed Tailscale keys remain protected GitHub inputs,
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

## Tailscale CI cutover

Phase 2b moves eight workflows to pre-signed reusable ephemeral Tailscale keys
while retaining Tailnet Lock. Plan and apply use separate protected environment
keys; Cordium uses its own repository key and independent native OIDC policy.
Every joined runner verifies its exact single tag and tailnet before live work.
The hosted Ubuntu runner owns a private per-job state directory that is never
cached or uploaded; daemon logout alone does not delete that directory.

Before merging this source, complete canonical DNS/API acceptance, deploy the
operator API proxy and plan admission/RBAC, and publish keys through the fixed
reviewed `scripts/tailscale-ci-configure.py` helper. After merge, require protected
plan with denied real writes, exact-main apply, diagnostics, both publishers,
and Cordium execution, denial and cleanup checks. Source validation alone does
not establish these live outcomes.

The operator proxy kubeconfig contains no bearer token. Native catalog calls
use canonical mesh TLS but retain their short-lived Octelium authorization.
Legacy catalog, Tunnel and credentials stay until replacement acceptance; any
legacy CI rollback first restores the prior reviewed workflow transport.
Rotate provider generations before 60 days, republish signed keys, verify new
CI runs, then explicitly retire previous cached signing authorities. Preserve
the corrected separate authority/wrapper cache contract in the
[provider runbook](../../IaC/modules/tailscale-access/README.md).
