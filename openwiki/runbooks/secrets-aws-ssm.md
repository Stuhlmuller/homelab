---
type: runbook
title: "AWS SSM Secret References"
description: "SSM and ExternalSecret contracts plus coordinated Multica PostgreSQL password rotation on an initialized persistent volume."
tags: ["runbook", "secrets", "aws"]
sources:
  - id: openwiki-source-664c834cf8c51093d63fbef4
    resource: repo://.github/workflows/openclaw-enterprise-model-credential.yml
  - id: openwiki-source-fd05994eb55b0e1cf42320bb
    resource: repo://clusters/homelab/apps/harbor/bootstrap-job.yaml
  - id: openwiki-source-64bca48d4f10b0676e24742b
    resource: repo://clusters/homelab/apps/harbor/externalsecret.yaml
  - id: openwiki-source-584942349e9deaf323c58e09
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/externalsecret.yaml
  - id: openwiki-source-878d8aa0884abae2a8194701
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/README.md
  - id: openwiki-source-9268fd97f2c4ec8553f9ecb8
    resource: repo://clusters/homelab/apps/openclaw-enterprise/README.md
  - id: openwiki-source-c728e68797517895d00bd9f9
    resource: repo://clusters/homelab/apps/renovate/cronjob.yaml
  - id: openwiki-source-6680389f3ee90f86c4c9a782
    resource: repo://clusters/homelab/apps/renovate/externalsecret.yaml
  - id: openwiki-source-01fc0bedc522f2abd58d6698
    resource: repo://clusters/homelab/apps/renovate/README.md
  - id: openwiki-source-f19aa740c5d820d4dd28114e
    resource: repo://docs/operator-infrastructure.md
  - id: openwiki-source-2170f836209310971c5e7b70
    resource: repo://docs/secrets-aws-ssm.md
  - id: openwiki-source-1f0ad12bbff1986d64be6620
    resource: repo://IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl
  - id: openwiki-source-fdfe98760ed73d2ac287a83c
    resource: repo://scripts/openclaw-enterprise-startup.py
generated: { by: "codex", at: "2026-10-20T05:58:23.168Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-20T06:35:13.441Z
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

## Renovate App transfer and role retirement

The [Renovate runbook](../../clusters/homelab/apps/renovate/README.md) declares
two fixed SSM parameters for the existing GitHub App issuer and private key.
The [2026-10-19 operator receipt](../../docs/operator-infrastructure.md#renovate-app-credential-transfer-and-role-retirement)
records a successful companion transfer: both parameters reached version 2,
then `automation/renovate` refreshed with `Ready=True`; the CronJob stayed
suspended with no Job. Inspect only parameter and Secret metadata, never values.
Current IAM source removes the temporary exact-scope OIDC writer role from
desired state. After [#1390](https://github.com/Stuhlmuller/homelab/pull/1390)
merged, an operator applied a private, un-targeted saved plan deleting only
that role and inline policy. Read-only IAM lookup returned `NoSuchEntity`, and
a fresh full-unit plan had no changes. A later rotation needs a reviewed
reintroduction of the exact-scope grant. The CronJob is now declared
unsuspended on an hourly UTC schedule in full dry-run mode. Its earlier 19:00
and 20:00 UTC Jobs each finished all eight eligible repositories with no
reported errors. The legacy GitHub Action remains the only writer. Full App-policy parity, fault recovery,
the old-writer workflow deletion, guarded Actions-key retirement, and cluster
writer activation remain separate gates.

## OpenClaw Enterprise model key

The fresh Enterprise agent uses only
`/homelab/openclaw-enterprise/model-api-key`. The protected
[writer workflow](../../.github/workflows/openclaw-enterprise-model-credential.yml)
validates an owner-supplied OpenRouter key and binds the write to exact current
`main`; it does not copy the old OpenClaw or LiteLLM values. No key has been
supplied. The placeholder blocks activation and provider acceptance until a
real key is transferred, projected, and tested. See the
[canonical secret contract](../../docs/secrets-aws-ssm.md#openclaw-enterprise-credential-contract).

The dormant [foundation](../../clusters/homelab/apps/openclaw-enterprise-foundation/README.md)
declares eight retained `OnChange` ExternalSecret targets across
`openclaw-system` and `openclaw-agents`. `occ-database` templates separate
application and migration URLs from generated passwords; both require
PostgreSQL `verify-full` TLS against the declared retained root CA. The admin
and backup passwords remain in separate Secrets. Rotation needs a committed
`generated-secret-revision` advance and consumer verification. The manifests
are not registered with Argo, so source alone proves no SSM value, projected
Secret, issued certificate, or running database.

The reviewed [`installation.yaml`](../../clusters/homelab/apps/openclaw-enterprise/installation.yaml)
contains non-secret startup configuration. It is separate from those distinct SSM
credentials. The protected startup workflow copies its exact bytes into a
versioned immutable Kubernetes Secret because the stock chart mounts that
Secret at startup. Initial creation precedes the installation ID; T041 must
bind and attest that metadata after bootstrap before reconciliation can run.

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
`IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl` catalog source and
rendered into the `IaC/live/aws-ssm-parameters` OpenTofu stack, so do not
hand-edit
`/homelab/multica/postgres-password`; the next apply would restore the
repository-owned generated value.

Rotate it through a reviewed change window so the generated parameter, database
role, and consumers move together.

1. Open a reviewed PR that changes the declared rotation trigger or keeper for
   `/homelab/multica/postgres-password` in
   `IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl`. If the
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
