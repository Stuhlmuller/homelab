---
type: runbook
title: "CI/CD"
description: "Trusted Terragrunt plan and exact-SHA apply workflows, Policy Bot merge rules, environment approvals, and credential recovery."
tags: ["runbook", "ci", "github-actions"]
sources:
  - id: openwiki-source-29ced481494f3a85c0d7921b
    resource: repo://.github/workflows/terragrunt-apply.yml
  - id: openwiki-source-885831275c8e751281369a80
    resource: repo://.github/workflows/terragrunt-plan.yml
  - id: openwiki-source-e0d1dba87aa9213350b1234a
    resource: repo://docs/ci-cd.md
  - id: openwiki-source-e038674a313521b0f6eadc03
    resource: repo://docs/cordium-ci.md
  - id: openwiki-source-1247eded2dab9841fec2a345
    resource: repo://docs/nix-cache.md
  - id: openwiki-source-47792446a9e092544c3c1857
    resource: repo://scripts/ci/nix-checks.sh
  - id: openwiki-source-7f41167da18dbfa043cfc3ca
    resource: repo://scripts/ci/static-checks.sh
  - id: openwiki-source-de7fdd1af72d2845e129e766
    resource: repo://scripts/entra-ci-configure.py
  - id: openwiki-source-6f8ea3753bc76b21d99fe402
    resource: repo://scripts/tailscale-ci-configure.py
generated: { by: "codex", at: "2026-10-11T04:35:18.448Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-11T06:23:22.000Z
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
`14700233` required zero approving reviews while both CI environments separately
required owner approval. The canonical guide's contrary production guidance was
stale; it was corrected on 2026-10-11 UTC after verifying both live environments
and the upstream `github-iac` declarations.

The [environment guard](../../scripts/entra-ci-configure.py) requires exactly the
configured owner reviewer, disables administrator bypass and allows self-review.
Production restricts deployment to protected branches; the workflow additionally
requires the exact current `main` revision before using credentials. The
[Tailscale publisher](../../scripts/tailscale-ci-configure.py) reuses the guard
and refuses publication if protection differs. Policy Bot approval does not
remove these environment gates; plans and applies still require owner approval.

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

## Signed offline validation

Static workflows obtain cache URL/key policy from protected main, then verify or
build the expected Nix offline-test and manifest-policy outputs. The remaining
static wrapper still runs fresh provider, network and security checks. The
trusted PR's protected live plan remains fresh and separately owner-reviewed.
Neither a cached result nor a green static job authorizes production apply.

Use the [signed cache runbook](../../docs/nix-cache.md) for local validation,
Linux priming, key rotation and rollback. The declared builder is disposable;
its signing key remains local. Deployment, full build and warm CI reuse are
separate acceptance steps. See the [check flow](../architecture/gitops-flow.md#signed-offline-ci-checks).

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
