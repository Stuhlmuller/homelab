---
type: operation
title: "State Encryption"
description: "Separate runtime SSM and OpenTofu encryption keys, S3 Bucket Keys ownership, and preservation of confidential recovery archives."
tags: ["operations", "security", "storage"]
---

# State Encryption

Runtime SSM SecureStrings use AWS-managed `alias/aws/ssm` in `us-west-2`.
OpenTofu retains `alias/homelab-opentofu` in `us-east-1` for client-side state
and plan encryption. These keys have separate ownership and purposes.

The shared [`IaC/root.hcl`](../../IaC/root.hcl) owns client-side state and saved-plan encryption through
`remote_state.encryption`. Units, including temporary retirement configurations, inherit that policy; reusable
modules no longer declare their own encryption blocks or accept encryption-only inputs. Use the pinned
Terragrunt v1.2.2 development shell or a newer supported generator; the root rejects older versions.

Terragrunt generates provider and AES-GCM method blocks named `default`. The policy sets
`encrypted_metadata_alias = "key_provider.aws_kms.main"` to retain the key-provider metadata identity stored with
previously encrypted records. It does not preserve the former method block's label. The KMS key, region and
existing backend paths remain unchanged. New state and saved plans use AES-GCM.

The exact Homelab units in `legacy_state_units` and the shared SSM parameter
unit may read legacy state that predates client-side encryption. The SSM unit
owns its read exception, which is needed to plan the declared Bedrock reader
grant. After each declared apply, verify the encrypted write and remove the
corresponding fallback. For previously encrypted modules, the metadata alias
preserves compatibility with the old policy. Newly protected units must retain
equivalent encryption after their first ciphertext write,
including during a source rollback, until a separate migration is designed. See the
[state encryption guide](../../docs/state-encryption.md) for verification limits, plaintext adoption and safe
rollback boundaries. A source revert is not a state restore.

`IaC/homelab/us-west-2/operator/state-bucket-encryption` manages the existing S3 backend bucket's
encryption settings through `IaC/terragrunt-catalog/modules/aws-s3-bucket-encryption`. S3 Bucket
Keys are enabled; SSE-KMS, version history and OpenTofu client encryption remain
required. Bucket keys reduce S3-originated KMS requests, not OpenTofu's direct
client-side calls. The operator-owned unit is outside workload CI and has
`prevent_destroy` protection.

Validate and plan changes through that generated unit, review the saved plan,
and apply that exact plan through the documented operator workflow. Verify
`BucketKeyEnabled: true` using read-only bucket encryption inspection and require
a no-change follow-up plan. To disable bucket keys, change `bucket_key_enabled`
in the catalog source, regenerate, validate, plan and apply the same unit;
retain encryption and existing keys. Objects already using bucket keys remain
readable.

## Confidential Recovery Archives

The state bucket retains confidential copies of 128 SSM parameter versions and
60 old homelab state versions under `IaC/homelab/migrations/`. The SSM archive is
`ssm-aws-managed-2026-09-05/history.json`; state copies are beneath
`legacy-state-2026-09-05/`. These are recovery data, not active backends. They
use AWS-managed S3 encryption independently of the removed customer keys.
Do not delete these objects when cleaning repository artifacts, download them
into a public workspace, or publish their contents.

Recover a secret through a separately reviewed repository-owned restore path
using its archived name, version, value and labels. Do not apply old state as
a recovery test. The archived source values were verified on September 5, 2026;
this records retained recovery material, not a new restore exercise.

Related: [Storage And State](../architecture/storage-and-state.md),
[Secrets And Identity](../architecture/secrets-and-identity.md), [GitOps Flow](../architecture/gitops-flow.md).

The bootstrap Helm release also uses the local catalog module. Its former pinned
external module carried a second encryption block, which conflicts with the
root-generated backend policy. The local copy preserves `helm_release.this`,
provider constraints and all release inputs/outputs while removing that duplicate
policy; no backend key or resource address migration is involved.
