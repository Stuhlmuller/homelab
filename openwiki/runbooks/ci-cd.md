---
type: runbook
title: "CI/CD"
description: "Trusted Terragrunt plan and exact-SHA apply workflows, Policy Bot merge rules, environment approvals, and credential recovery."
tags: ["runbook", "ci", "github-actions"]
sources:
  - id: openwiki-source-28a7f340da431caf1c218c7d
    resource: repo://.github/workflows/cordium-runner-canary.yml
  - id: openwiki-source-36db39acd9400bc022704939
    resource: repo://.github/workflows/cordium-runner-credentials.yml
  - id: openwiki-source-d63f608fcb391d5edcf496e7
    resource: repo://.github/workflows/cordium-runner-images.yml
  - id: openwiki-source-a793a7dd08d0dc13de84207b
    resource: repo://.github/workflows/cordium-runner-publish.yml
  - id: openwiki-source-ae9e276e4f1f0876814f04a2
    resource: repo://.github/workflows/harbor-native-chainguard-receipt-provenance.yml
  - id: openwiki-source-9a01f0687eaa075cf78c3abc
    resource: repo://.github/workflows/image-automation.yml
  - id: openwiki-source-2ab88915e37908e92fe8ef01
    resource: repo://.github/workflows/lint.yml
  - id: openwiki-source-3b8a5a1dece086403bc8ab75
    resource: repo://.github/workflows/nofx-images.yml
  - id: openwiki-source-66763af1d94960a2aaf14e95
    resource: repo://.github/workflows/openclaw-config.yml
  - id: openwiki-source-664c834cf8c51093d63fbef4
    resource: repo://.github/workflows/openclaw-enterprise-model-credential.yml
  - id: openwiki-source-c0ca5e405a32db452e0a5896
    resource: repo://.github/workflows/openclaw-enterprise-startup.yml
  - id: openwiki-source-f85a2f83ac2451fd051bfc74
    resource: repo://.github/workflows/platform-maintenance.yml
  - id: openwiki-source-50e1601d2f23b472521e5c0f
    resource: repo://builds/cordium-runner/README.md
  - id: openwiki-source-e0d1dba87aa9213350b1234a
    resource: repo://docs/ci-cd.md
  - id: openwiki-source-2170f836209310971c5e7b70
    resource: repo://docs/secrets-aws-ssm.md
  - id: openwiki-source-a176afce8833edc1068e3844
    resource: repo://scripts/ci/octelium-private-kubernetes-apply-test.py
  - id: openwiki-source-2b445535596913b662665f3c
    resource: repo://scripts/ci/octelium-private-kubernetes-apply.sh
  - id: openwiki-source-020791e1237c864b31f43a39
    resource: repo://scripts/ci/offline-static-checks.sh
  - id: openwiki-source-379810dcab1205ffb941d2cb
    resource: repo://scripts/ci/platform-maintenance-stage.sh
  - id: openwiki-source-13711977c9ca794932b4c8ee
    resource: repo://scripts/config/platform-maintenance.json
  - id: openwiki-source-fdfe98760ed73d2ac287a83c
    resource: repo://scripts/openclaw-enterprise-startup.py
generated: { by: "codex", at: "2026-10-19T21:54:24.498Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-20T03:43:08.437Z
---

# CI/CD

Canonical runbook: [`docs/ci-cd.md`](../../docs/ci-cd.md)

Pull requests always emit the aggregate `Terragrunt Gate`; only trusted changes
to live inputs enter the protected plan environment. Pushes to `main` emit an
exact-SHA apply request, and an operator dispatches the protected apply. AWS,
Azure, Kubernetes, and Octelium credentials remain GitHub environment inputs,
while desired state stays in repository-owned files.

The separate Octelium Private Kubernetes Apply dispatch verifies the selected
`main` commit before the protected job. Its fixed helper rechecks current `main`
immediately before each of two catalog writes; a failed lookup or newer commit
stops the next write. The second write must report no changes. These source
guards have not been exercised by a live dispatch in this update.

Policy Bot automatically approves PRs through `requires.count: 0` in
[`.policy.yml`](../../.policy.yml); human and Codex reviews are optional.

The pull-request `Lint` job reports its own conclusion without commit-status
write permission. The static gate rejects that permission in any PR workflow;
the trusted-base native Chainguard receipt workflow alone sets its provenance
status after checking the current main and PR head.
Required GitHub checks and explicit Stuhlmuller organization-member disapproval
still block merges. The policy takes effect from the target branch after merge;
revert `.policy.yml` to restore review requirements.

Read-only GitHub inspection on 2026-10-17 UTC confirmed that `main` ruleset
`14700233` still requires the seven documented checks. `homelab-plan` has no
environment protection rules; `homelab-production` has its branch policy and
no required reviewer. The older October 6 reviewer snapshot is superseded.
Re-read live settings before changing environment or branch protections.

NOFX image builds, OpenClaw native configuration checks, and Image automation
verification now run on matching `main` pushes or reviewed manual dispatches,
without optional pull-request runs. Image automation no longer observes every
five minutes; dispatch its `verify` operation from `main` for a deliberate
journal check. Required pull-request checks retain their existing producers.

The separate [OpenClaw Enterprise model-credential workflow](../../.github/workflows/openclaw-enterprise-model-credential.yml)
accepts only an exact current-`main` dispatch into `homelab-production`. Its
protected job validates the owner-supplied OpenRouter key, then writes only the
new Enterprise SSM parameter. It has not run because the key is not yet supplied;
this source change does not activate Enterprise.

The [Enterprise startup workflow](../../.github/workflows/openclaw-enterprise-startup.yml)
is a separate protected, exact-current-`main` dispatch. After static checks
and the production environment gate, its pinned script creates or attests only
the versioned immutable Installation Secret from reviewed repository bytes.
The create-only path does not register the dormant Application or run an Agent;
the post-bootstrap installation-ID annotation and live Pod binding remain
separate proof work.

The separate [Platform Maintenance workflow](../../.github/workflows/platform-maintenance.yml)
accepts fixed inspect, canary and upgrade stages only from the exact current
`main` commit. It runs static checks before the protected job, rechecks the SHA
before AWS credentials, and verifies the pinned stage helper before execution.
The executor keeps activation and canary placement disabled until private
recovery, image-publication and isolated-node evidence is available; no upgrade
stage has run from this source change.

See [Validation Gates](../operations/validation-gates.md) and [GitOps Flow](../architecture/gitops-flow.md).

Cordium runner bootstrap is staged as separate exact-main workflows for
credential intake, fixed image builds, protected Harbor publication, and a
canary. The controller would provision one JIT runner per job with private
file-backed credentials and verify Workspace, Kubernetes, and GitHub cleanup.
The pool remains disabled and existing job selectors stay unchanged. The
[runner contract](../../builds/cordium-runner/README.md) lists the live
isolation, publication, cold-pull, canary, and recovery evidence required
before a reviewed selector cutover.

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
