---
name: homelab-release-verification
description: Deliver an authorized homelab rollout and verify the original live behavior after merge. Use for deployment, rollout recovery, or acceptance checks; code-only changes do not require deployment.
---

# Homelab Release Verification

Read the affected workload README and [CI delivery contract](../../../docs/ci-cd.md).
Use the user's existing authorization; this skill does not itself authorize
workflow dispatches or production changes.

## Choose the delivery path

- Runtime manifests or values: Argo CD follows reviewed `main`; verify the
  Application's observed revision after merge.
- Application registration, infrastructure, or secret declarations: use
  [Terragrunt Apply](../../../.github/workflows/terragrunt-apply.yml) with exact
  current `main` as `expected_sha`. Read the selected `argocd_app` path in
  [the apply script](../../../scripts/ci/terragrunt-apply.sh) before claiming
  its scope. Some targets reconcile shared SSM/IAM and app-specific storage;
  targeted runs do not advance the full-apply checkpoint.
- Custom image or new mirrored digest: finish the relevant publication
  workflow before merging its consuming reference. See
  [Harbor publication](../homelab-harbor-images/SKILL.md).
- Operator-owned bootstrap permissions stay under `IaC/operator`; the workload
  CI role cannot administer itself. Use the documented operator path when
  the requested rollout needs it.

## Prove each milestone

1. Run the relevant [validation gates](../../../docs/knowledge-base/operations/validation-gates.md),
   including static checks, Conftest and the affected render/plan. Record actual
   failures or unavailable checks before production work.
2. Record the merged commit and, when applicable, the exact workflow run ID,
   dispatched SHA and successful conclusion. A queued run is not delivery.
3. Check the upstream Applications, secret store, CRDs and storage required by
   the target. Terragrunt ordering does not prove runtime readiness.
4. Verify Argo CD observed the intended revision, finished its operation, and
   reports Synced/Healthy; verify the workload's rollout and actual image digest
   when images changed. Use the [readiness runbook](../../../docs/validation-runbook.md)
   and app-specific acceptance commands.
5. Exercise the original user action through its real access/data path. A
   working ingress or health endpoint does not prove a Desktop client,
   attributed model generation, login, backtest, or persistent write works.
   Read-only probes are preferred; use mutations only within the task's scope.

For failure, inspect the existing run/operation before retrying. Fix desired
state in the repo; do not patch, restart or force-sync live resources ad hoc.
Use [rollback guidance](../../../docs/rollback-argocd-apps.md) and the workload's
state/backup requirements. Report validation, merge, deployment and live
acceptance separately; record unresolved operational findings in the relevant
knowledge-base note.
