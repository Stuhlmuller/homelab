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
  - id: openwiki-source-db6cf97d787f19eab7b1a68b
    resource: repo://.github/workflows/openclaw-enterprise-images.yml
  - id: openwiki-source-664c834cf8c51093d63fbef4
    resource: repo://.github/workflows/openclaw-enterprise-model-credential.yml
  - id: openwiki-source-02c6601e3ee1ac6a7a26e042
    resource: repo://.github/workflows/openclaw-enterprise-operations.yml
  - id: openwiki-source-c0ca5e405a32db452e0a5896
    resource: repo://.github/workflows/openclaw-enterprise-startup.yml
  - id: openwiki-source-f85a2f83ac2451fd051bfc74
    resource: repo://.github/workflows/platform-maintenance.yml
  - id: openwiki-source-885831275c8e751281369a80
    resource: repo://.github/workflows/terragrunt-plan.yml
  - id: openwiki-source-50e1601d2f23b472521e5c0f
    resource: repo://builds/cordium-runner/README.md
  - id: openwiki-source-cd4f78e3208dc4d64a31699a
    resource: repo://builds/openclaw-enterprise/build-operator.sh
  - id: openwiki-source-d2d8ff2161af78b658d004f0
    resource: repo://clusters/homelab/apps/openclaw-enterprise-operator/README.md
  - id: openwiki-source-e0d1dba87aa9213350b1234a
    resource: repo://docs/ci-cd.md
  - id: openwiki-source-df5b234ace5ca38a67ae3b6b
    resource: repo://docs/evidence/openclaw-enterprise-acceptance.md
  - id: openwiki-source-b3b14c71f8a81de8a3b71c02
    resource: repo://docs/examples/octelium/homelab-services.yaml
  - id: openwiki-source-f2b6230f4caf06e7eab9bc66
    resource: repo://docs/harbor-image-mirroring.md
  - id: openwiki-source-2170f836209310971c5e7b70
    resource: repo://docs/secrets-aws-ssm.md
  - id: openwiki-source-bdda46b717c2e2415e19e8f3
    resource: repo://IaC/root.hcl
  - id: openwiki-source-d15d8af567654cd0f94c3158
    resource: repo://IaC/terragrunt-catalog/units/bootstrap/argocd/terragrunt.hcl
  - id: openwiki-source-fdad4f74fd023e19134fcc88
    resource: repo://policy/workflows_test.rego
  - id: openwiki-source-8853fb993dc68b93d8f20498
    resource: repo://policy/workflows.rego
  - id: openwiki-source-6044cd3de00b52da78c6cf44
    resource: repo://scripts/ci/harbor-native-chainguard-receipt-import.py
  - id: openwiki-source-d9d387d4c8e269e62340179d
    resource: repo://scripts/ci/harbor-publish.sh
  - id: openwiki-source-a176afce8833edc1068e3844
    resource: repo://scripts/ci/octelium-private-kubernetes-apply-test.py
  - id: openwiki-source-2b445535596913b662665f3c
    resource: repo://scripts/ci/octelium-private-kubernetes-apply.sh
  - id: openwiki-source-020791e1237c864b31f43a39
    resource: repo://scripts/ci/offline-static-checks.sh
  - id: openwiki-source-856035e595a8b9b128dcb0a8
    resource: repo://scripts/ci/openclaw-enterprise-journal-operator.py
  - id: openwiki-source-b3bdcadf54edf75020440bdd
    resource: repo://scripts/ci/openclaw-enterprise-operations.sh
  - id: openwiki-source-38f54948f5bf90d0cb9bddb7
    resource: repo://scripts/ci/openclaw-enterprise-stage.sh
  - id: openwiki-source-379810dcab1205ffb941d2cb
    resource: repo://scripts/ci/platform-maintenance-stage.sh
  - id: openwiki-source-8564baaf10e1673a998e5188
    resource: repo://scripts/ci/terragrunt-apply.sh
  - id: openwiki-source-181c84b7cc75d240ee7654cc
    resource: repo://scripts/ci/terragrunt-current-main.sh
  - id: openwiki-source-d4c5f4ea43a9c10ac5e00082
    resource: repo://scripts/ci/terragrunt-plan-stage-test.py
  - id: openwiki-source-60b00db0363e7f9e27d7fa7f
    resource: repo://scripts/ci/terragrunt-plan.sh
  - id: openwiki-source-d2206c7f78c1ec59c3551c13
    resource: repo://scripts/config/openclaw-enterprise.json
  - id: openwiki-source-13711977c9ca794932b4c8ee
    resource: repo://scripts/config/platform-maintenance.json
  - id: openwiki-source-79ade26d1f528d349dc08fed
    resource: repo://scripts/network-policy-canary-node.py
  - id: openwiki-source-1d91dece74882a3fae04c364
    resource: repo://scripts/network-policy-cleanup.py
  - id: openwiki-source-ba849f5dbd0942cee0b0087d
    resource: repo://scripts/network-policy-ownership.py
  - id: openwiki-source-fdfe98760ed73d2ac287a83c
    resource: repo://scripts/openclaw-enterprise-startup.py
generated: { by: "codex", at: "2026-10-21T00:34:35.293Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-23T05:15:07.566Z
---

# CI/CD

Canonical runbook: [`docs/ci-cd.md`](../../docs/ci-cd.md)

Pull requests always emit the aggregate `Terragrunt Gate`; only trusted changes
to live inputs enter the protected plan environment. Pushes to `main` emit an
exact-SHA apply request, and an operator dispatches the protected apply. AWS,
Azure, Kubernetes, and Octelium credentials remain GitHub environment inputs,
while desired state stays in repository-owned files.

The production apply rejects a dispatch whose SHA is no longer current `main`.
It rechecks `main` before each live import or apply. Terragrunt's root hook
repeats the check for each unit in a multi-unit apply, and the Argo CD
bootstrap hook checks before each self-management manifest write. A failed
lookup stops the write. These source guards await a live apply run.

The Octelium catalog stages a separate `homelab-ci-plan` User and a
read-or-dry-run Policy for `kubernetes-api-ci`. Merging the source neither
applies the catalog nor issues a plan token; the PR plan still reads its
environment secret.

The separate Octelium Private Kubernetes Apply dispatch verifies the selected
`main` commit before the protected job. Its fixed helper rechecks current `main`
immediately before each of two catalog writes; a failed lookup or newer commit
stops the next write. The second write must report no changes. These source
guards have not been exercised by a live dispatch in this update.

An AzureAD stack, shared root, or plan-input change requires
`AZUREAD_CLIENT_ID` and `AZUREAD_TENANT_ID` in `homelab-plan` plus a complete
GitHub OIDC session. Missing inputs fail `Terragrunt Plan`. Restore the plan
identity through the [Entra provider runbook](../../docs/entra-terraform-provider.md),
rerun the protected PR plan, and verify `Terragrunt Gate` before merging.
If the static job cannot read the PR base diff, it fails before deciding to
skip the live plan.

Policy Bot automatically approves PRs through `requires.count: 0` in
[`.policy.yml`](../../.policy.yml); human and Codex reviews are optional.

The pull-request `Lint` job reports its own conclusion without commit-status
write permission. The static gate rejects that permission in any PR workflow;
the trusted-base native Chainguard receipt workflow alone sets its provenance
status after checking the current main and PR head. Its tightly pinned
`pull_request_target` exception checks only the event PR head after confirming
it remains in the open `main` PR list. On `main` pushes it compares exact
base/head native receipt entries and rechecks changed entries; unreadable state
or an absent receipts map also requires verification. Unrelated heads keep
their prior status.
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

The protected [Enterprise images workflow](../../.github/workflows/openclaw-enterprise-images.yml)
builds the stock controller, runtime, and CLI plus the source-bound journal
operator from exact current `main`. The operator build and non-root smoke checks
run before registry credentials; publication signs and completely pulls all
four images. No signed operator digest has been accepted yet. A failed run
reports only a fixed publication phase in its job summary; private transport
and registry output remains encrypted. A failure produces no accepted image
receipt. Retry from current `main` after resolving that phase.

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

The [Enterprise operations workflow](../../.github/workflows/openclaw-enterprise-operations.yml)
keeps legacy retention behind `legacy_stage` and reserves fixed
`bind-installation`, `full-sync`, `reconcile`, `stop`, `verification`, `restore`
and `acceptance` Enterprise selections. Select exactly one stage. Each protected
job rechecks exact current `main` and shares a non-canceling production queue.
The binding lane pins the reviewed binder and requires an owner-controlled 0600
bootstrap service-key file; no hosted-runner delivery is declared. The other
stages call a pinned [guard](../../scripts/ci/openclaw-enterprise-stage.sh).
Its `full-sync` branch invokes the pinned
[helper](../../scripts/ci/openclaw-enterprise-full-sync.sh), but the committed
`unselected` installation phase blocks sync before Kubernetes access.
`reconcile`, `stop`, and `verification` now call the pinned
[one-shot Job dispatcher](../../scripts/ci/openclaw-enterprise-journal-operator.py)
only after `journalOperator.enabled` is true. It rechecks current `main`,
source and configuration identity, retained journal and bootstrap claim/PV
identity, and prior Job state before a fresh Job per workflow attempt. The
[operator bundle](../../clusters/homelab/apps/openclaw-enterprise-operator/README.md)
declares a local journal claim and scoped proof permissions but is absent from
active GitOps; the disabled gate stops before Job creation. The hosted runner
does not mount the private journal. `restore` and `acceptance` still exit before
mutation pending separate recovery and owner-session proof. No Enterprise
stage has passed live acceptance.

For legacy `publish-archive`, the workflow now reports fixed public
post-upload phases for archive metadata, receipt publication and both restore
transfers while withholding private diagnostics. Run `39466313228` completed
the bounded upload but failed under the former broad `publication-version`
phase. No final offsite restore receipt exists; independent `verify` was not
dispatched. Retry only from a fresh exact-current-`main` source after review.

The startup and operations [workflow policy](../../policy/workflows.rego) rules
accept only `workflow_dispatch`. Regression fixtures reject an added
`workflow_call` event, so another workflow cannot reuse those protected jobs
without manual dispatch. They also reject unreviewed workflow or job run
defaults and environment, step shell or working-directory overrides, and
`BASH_ENV` or `ENV` on any step. The credentialed legacy stage binds its exact
four-variable environment. This is source validation, not a live execution
receipt.

The separate [Platform Maintenance workflow](../../.github/workflows/platform-maintenance.yml)
accepts fixed inspect, canary and upgrade stages only from the exact current
`main` commit. It runs static checks before the protected job, rechecks the SHA
before AWS credentials, and verifies the pinned stage helper before execution.
The executor keeps activation and canary placement disabled until private
recovery, image-publication and isolated-node evidence is available; no upgrade
stage has run from this source change.

The [workflow policy](../../policy/workflows.rego) accepts only manual
`workflow_dispatch`, requires explicit empty workflow permissions, and pins both
jobs' commands, actions, settings and private credential mapping. Regression
tests reject an added reusable `workflow_call` trigger, run defaults, environment
overrides, and custom shells that could bypass the reviewed commands. This is a
source guard, not live readiness.

The protected canary and firewall stages require a configured canary node and
exact-current-main dispatch. Admission verifies private placement and
adds the dedicated isolation taint before the selector label. It checks the
cluster-wide label selector before mutation, immediately before labeling, and
after the patch. A preflight conflict blocks mutation; a later conflict
retains the taint and removes this Node's label. After the exact qualify →
fixture-prune → firewall-prune commits, with unrelated merges allowed only when
operational source and Nix flake inputs stay invariant, `ownership-capture`
requires the live
fixture namespace and all fixture workloads to be absent and stores a
versioned private snapshot. `ownership-approve` requires the owner actor and
an exact reviewed digest before it writes an immutable capture-run-specific
receipt. `owned-cleanup` loads that receipt under current main and the
original placement under the qualify SHA, then records a private attempt
before deletion. Capture through release also require a complete node Pod
list matching the reviewed system DaemonSet UIDs and validated cleanup Pod
while it runs. A system Pod restart blocks this immutable placement path until
separately reviewed recovery. Release verifies the same source chain and
reviewed cleanup run, removes the label, waits for cleanup DaemonSet Pods to
disappear cluster-wide, then rechecks that only reviewed system Pods remain
before removing the taint. An incomplete inventory or changed Pod retains
isolation.

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
