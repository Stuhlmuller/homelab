---
type: runbook
title: "AWS SSM Secret References"
description: "SSM and ExternalSecret contracts plus coordinated Multica PostgreSQL password rotation on an initialized persistent volume."
tags: ["runbook", "secrets", "aws"]
sources:
  - id: openwiki-source-fd05994eb55b0e1cf42320bb
    resource: repo://clusters/homelab/apps/harbor/bootstrap-job.yaml
  - id: openwiki-source-64bca48d4f10b0676e24742b
    resource: repo://clusters/homelab/apps/harbor/externalsecret.yaml
  - id: openwiki-source-01fc0bedc522f2abd58d6698
    resource: repo://clusters/homelab/apps/renovate/README.md
  - id: openwiki-source-2170f836209310971c5e7b70
    resource: repo://docs/secrets-aws-ssm.md
  - id: openwiki-source-cf9e058040b1a15ca636bb42
    resource: repo://IaC/.catalog/units/live/aws-ssm-parameters/terragrunt.hcl
  - id: openwiki-source-4fa6e8b8348f9583e76afe30
    resource: repo://IaC/modules/aws-github-actions-role-policy/main.tf
generated: { by: "codex", at: "2026-10-18T20:54:44.446Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-18T20:54:44.446Z
---

# AWS SSM Secret References

Canonical runbook: [`docs/secrets-aws-ssm.md`](../../docs/secrets-aws-ssm.md)

## Image automation identities

The Chainguard/Image Updater contract uses two future GitHub App identities:
the proposer may write only `codex/image-updater-proposals`, while the promoter
is used only by the reviewed `homelab-production` workflow for a non-force main
update. Do not reuse the Terragrunt apply role or commit private keys. Add new
SSM references and exact reader grants only in the companion governance change;
until then the updater stays at zero replicas and no ExternalSecret is enabled.

Commit SSM paths, ExternalSecret contracts, and safe placeholders only. Runtime
values stay outside git; External Secrets materializes application credentials
after the repository-managed bootstrap secret is available.

## Renovate App transfer (staged)

The [Renovate runbook](../../clusters/homelab/apps/renovate/README.md) declares
two fixed SSM placeholders for the existing GitHub App issuer and private key.
After a reviewed, private SSM plan, apply the temporary exact-scope OIDC transfer
role. The companion repository's protected workflow writes the existing App
credentials to those paths; verify parameter metadata and a later
`automation/renovate` ExternalSecret refresh without reading values. Retire the
transfer grant through another reviewed plan before unsuspending the hourly
CronJob. This sequence is staged source, not a completed live transfer.

## Harbor native receipt prerequisite

The generated `/homelab/harbor/robot-scan-password` parameter is present as a
version 1 `SecureString`. Read-only IAM inspection confirmed its exact
External Secrets reader grant, and a targeted plan from `main` at `f6506136`
found no changes on 2026-10-18. The Harbor `OnChange` ExternalSecret still
needs GitOps reconciliation and a successful PostSync bootstrap before the
protected native receipt can run. See the [Harbor contract](../operations/harbor-oci.md).

## Multica PostgreSQL Password Rotation

The Multica chart reads `POSTGRES_PASSWORD` when the built-in PostgreSQL data
directory is initialized. On a retained, already-initialized PVC, refreshing
`multica-secrets` does not change the existing `multica` database role
password. The generated SSM value is declared in the committed
`IaC/.catalog/units/live/aws-ssm-parameters/terragrunt.hcl` catalog source and
rendered into the `IaC/live/aws-ssm-parameters` OpenTofu stack, so do not
hand-edit
`/homelab/multica/postgres-password`; the next apply would restore the
repository-owned generated value.

Rotate it through a reviewed change window so the generated parameter, database
role, and consumers move together.

1. Open a reviewed PR that changes the declared rotation trigger or keeper for
   `/homelab/multica/postgres-password` in
   `IaC/.catalog/units/live/aws-ssm-parameters/terragrunt.hcl`. If the
   generated-parameter workflow does not have an explicit keeper yet, add one
   before rotating.
2. regenerate the live stack, then plan and apply it so OpenTofu writes the new
   SecureString value to SSM.
3. Pause Multica writes through GitOps, such as a reviewed change that
   disables automated sync or scales the backend in desired state, then wait for
   Argo CD to report the paused state. Do not rely on manual `kubectl scale`
   while automated self-heal is enabled.
4. Read the new value from SSM in an operator shell without printing it in
   history or logs, then exec into the PostgreSQL pod while the old Secret still
   works and run `ALTER USER multica WITH PASSWORD '<new-password>';` through
   `psql` as the database superuser.
5. Bump `homelab.stuhlmuller.dev/generated-secret-revision` on both
   ExternalSecrets in `clusters/homelab/apps/multica/externalsecret.yaml` so
   External Secrets refreshes `multica-secrets` and `multica-backend-secrets`.
6. Confirm both target Secrets contain the new version, then roll the backend
   and PostgreSQL through repository-owned pod-template changes. Argo CD's Helm
   render cannot use the chart's live Secret checksum to trigger a restart.
7. Verify backend readiness, login/signup, and a simple workspace read/write
   before reopening writes.

If any step fails after the role password changes, either complete the Secret
refresh and pod restart or revert the rotation PR, regenerate and re-apply the generated
parameter stack, and run another `ALTER USER` back to the restored password
before bringing the backend up.

See [Secrets And Identity](../architecture/secrets-and-identity.md) and [Workload Inventory](../workloads/inventory.md).
