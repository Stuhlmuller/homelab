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

`IaC/operator/state-bucket-encryption` manages the existing S3 backend bucket's
encryption settings through `IaC/modules/aws-s3-bucket-encryption`. S3 Bucket
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
