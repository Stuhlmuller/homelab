# KMS Cost Audit — 2026-09-05

## AWS-managed SSM migration

The user subsequently requested execution of the migration. All 68 current
parameters now use `alias/aws/ssm`; verified each value unchanged against an
archive of all 128 pre-migration versions. The SSM unit applied 59 key-only
parameter updates and one reader-policy update. The repository migration
script migrated the remaining nine parameters owned by the Entra stacks.
All 24 ExternalSecrets report Ready. CloudTrail confirms Cordium's 13:33:08
and 13:38:08 UTC decrypts used the AWS-managed SSM key.

`scripts/migrate-ssm-aws-managed.py` uses the committed exact-name manifest at
`scripts/config/ssm-aws-managed-migration.json`. The `archive` action writes
once (`If-None-Match: *`) to the state bucket at
`IaC/homelab/migrations/ssm-aws-managed-2026-09-05/history.json`, explicitly
using `alias/aws/s3` with bucket keys. It reads the archive back, checks the
AWS-managed KMS ARN and SHA-256, and compares its complete contents. The
verified digest is
`429cecf01a684d38f917effb247714a4eac0feab9315594ee9831f4a40645cd9`.
The object contains secret history: retain it as confidential backup, never
download it into a public workspace or publish its contents.

The `migrate` action refuses unexpected source keys, version labels, values
changed since the archive, or concurrent version changes. It preserves current
values and tiers. Reruns skip already migrated values. `verify` performs the
same value/key checks without writes. Run through the normal AWS administrator
session, without injecting secrets into command arguments or environment:

```sh
python3 -m unittest discover -s scripts -p test_migrate_ssm_aws_managed.py
python3 scripts/migrate-ssm-aws-managed.py archive  # first run only
python3 scripts/migrate-ssm-aws-managed.py migrate
python3 scripts/migrate-ssm-aws-managed.py verify
```

The module and operator boundary support temporary access to both exact keys;
the final desired state selects only the AWS-managed key. The policy package
permits a one-time, 30-day retirement of only the archived SSM key UUID,
at `aws_kms_key.this[0]`. Other sensitive deletion and replacement plans remain
rejected. The reviewed retirement plan passed 112 combined plan-policy checks.
The old SSM key is now `PendingDeletion`, scheduled for October 5, 2026 at
13:43:43 UTC (30 days). Its alias was removed and temporary old-key reader
permissions were removed. This removes approximately $1/month in key fees.
Final plans for both the SSM and operator IAM units returned no changes.
All 68 values were verified again after the old key entered PendingDeletion.

Current values need no rollback: they are unchanged. Historical recovery uses
the archived parameter name/version/value and labels through a separately
reviewed repository-owned restore procedure. Original historical SSM versions
will stop decrypting after old-key deletion; their readable copies are in the
verified archive. Do not discard the archive when cleaning up migration code.

The user authorized the cross-project dependency audit and chose to retain
OpenTofu's east-region client-side key. The refreshed S3 inventory covered all
15 account buckets. Inspection of 6,953 other-project state versions found no
legacy-key references, wrapping-key dependencies, server-side encryption uses,
or Terraform ownership of that key. Another 43 filename matches were HTML
pages or gzip CloudTrail logs, not state files. All relevant JSON state
versions were readable; 92 other-project encrypted versions use the retained
east-region key. No state values or data keys were printed.

The exact legacy key and alias are now adopted into
`IaC/operator/legacy-kms-retirement`. Adoption imported two resources, set the
30-day deletion window, and enabled standard annual rotation without rotating
key material. The committed `retirement_requested = true` is the proposed
retirement: its saved plan deletes only that key and alias and passes the
policy gate. A second exact-UUID exception protects all other keys, including
the active OpenTofu key, from deletion. Automatic approval review rejected
executing the plan pending the user's explicit approval for this exact key
deletion. The legacy key remains enabled; no further savings are claimed yet.

After explicit approval, apply only the reviewed operator plan, verify the
legacy key is PendingDeletion with a 30-day date, and run archive verification
without the original key:

```sh
/private/tmp/homelab-kms-sdk/bin/python scripts/archive-legacy-homelab-state.py verify
```

The operator unit is generated from
`IaC/.catalog/units/operator/legacy-kms-retirement/terragrunt.hcl` and uses
`IaC/modules/aws-kms-key-retirement`. Keep `retirement_requested = true` after
retirement; normal re-applies must not recreate a key. Adoption requires an
explicit temporary false value and the existing key/alias import blocks.

The homelab-only history check resolved all 4,739 retained state-version key
dependencies: 515 client-encrypted versions use the retained east-region key,
60 use the legacy west-region key, and none use the retired SSM key. Remaining
versions have no OpenTofu client encryption layer. Key IDs were resolved by
KMS unwrap responses; searching ciphertext for UUID text is not reliable.
No decrypted resource values or data keys were printed.

All 60 legacy homelab states are additionally archived under `aws/s3` at
`IaC/homelab/migrations/legacy-state-2026-09-05/`. Each copy preserves the exact
decrypted state bytes and validates AES-GCM authentication, state lineage,
serial, AWS-managed server encryption, and full readback equality. Originals
remain untouched. `scripts/archive-legacy-homelab-state.py` uses the committed
exact-version manifest and the pinned dependencies in
`scripts/config/kms-migration-requirements.txt`. Reruns compare existing copies;
they never overwrite an archive. These are confidential recovery copies, not
active backends; never import or apply a retired Nomad stack merely to test them.

```sh
python3 -m venv /private/tmp/homelab-kms-sdk
/private/tmp/homelab-kms-sdk/bin/pip install -r scripts/config/kms-migration-requirements.txt
/private/tmp/homelab-kms-sdk/bin/python -m unittest discover -s scripts -p test_archive_legacy_homelab_state.py
/private/tmp/homelab-kms-sdk/bin/python scripts/archive-legacy-homelab-state.py
```

The archival AES-GCM format follows
[OpenTofu v1.11.5](https://github.com/opentofu/opentofu/blob/v1.11.5/internal/encryption/method/aesgcm/aesgcm.go).
The cross-project dependency check is complete. Exact deletion approval is
the remaining retirement gate; retain the active OpenTofu key.

The original audit below is a pre-migration snapshot.

## Scope and evidence

Read-only AWS inventory of the homelab account ending 8480 across all 18
enabled regions. Cost Explorer unblended KMS charges (USD):

| Month | Key storage | Requests | Total |
| --- | ---: | ---: | ---: |
| June 2026 | 2.99 | 0.05 | 3.04 |
| July 2026 | 2.99 | 0.00 | 2.99 |
| August 2026 | 2.98 | 0.07 | 3.05 |

September-to-date billing is estimated and incomplete. This is an account
audit, not an organization-wide bill audit.

19 keys exist: seven in `us-east-1`, twelve in `us-west-2`, none elsewhere.
16 have AWS-managed aliases and no monthly key-storage fee. Three enabled
customer-managed symmetric keys account for approximately $3/month:

| Region | Alias | Dependency and disposition |
| --- | --- | --- |
| us-east-1 | homelab-opentofu | Active S3 backend and OpenTofu client-side state encryption; retain |
| us-west-2 | homelab-opentofu | All 68 current SSM parameters reference this alias; retain |
| us-west-2 | tofu-encryption-key | Legacy candidate; no current repository reference, SSM reference, tags, or grants; retain pending historical ciphertext audit |

The runtime-secret key rotates annually, next scheduled May 2027. Rotation
is disabled on the other two keys. Monthly pricing is $1 per customer key,
with additional charges for its first two rotations; disabling a key does not
eliminate key storage charges. See [AWS KMS pricing](https://aws.amazon.com/kms/pricing/).

CloudTrail lookup by the legacy key UUID from June 8 returned only four
administrative inspection events from August 30 UTC; lookup by its full ARN
returned no events. A broader full-payload scan was stopped after five minutes
and is incomplete. This does **not** prove
the key is unused: cryptographic events can use ARN identifiers, logging is
bounded, and old ciphertext may be dormant. No key deletion is authorized by
this finding. Before retirement, inspect full KMS event payloads, retained
S3 versions and client-side encryption headers, backups, other state stores,
and owning projects. Migrate or explicitly retire every dependency through
repository-owned code, then review a 30-day scheduled-deletion plan. Potential
savings: approximately $1/month, not yet realized.

## Request-cost reduction

### Caller attribution follow-up

Bounded CloudTrail samples taken September 5 (300 most recent events per
region/action since September 1; all samples truncated, not monthly shares):

- West-region Decrypt: all 300 events, spanning about 25 hours, came from
  `external-secrets_aws-ssm-auth` through SSM for Cordium's agent-auth parameter.
  Its repository ExternalSecret polls every five minutes: approximately 288
  reads/day or 8,640 per 30 days. Other declared ExternalSecrets use OnChange.
- East-region GenerateDataKey: 295 of 300 events came directly from the
  OpenTofu KMS encryption provider in GitHub Terragrunt plan sessions. Five
  came through S3 during this operator audit/apply.
- East-region Decrypt: 135 of 300 events came directly from OpenTofu in CI plan
  sessions. Other events include S3, Lambda, and ACM/CloudFront operations.

Both plans and applies access encrypted state. OpenTofu also uses the KMS
provider for client-side state and saved-plan encryption, independently of
S3 server-side encryption. A plan can therefore generate KMS calls without
changing any infrastructure. Bucket keys cannot reduce those direct calls.
The samples show a continuous Cordium polling baseline plus CI plan bursts;
they do not establish the full month's caller proportions. The account also
contains non-homelab workloads, so not every KMS request originates in this repo.


The state bucket had SSE-KMS default encryption with `alias/aws/s3` and
`BucketKeyEnabled: false`. The homelab backend explicitly supplies its own
`alias/homelab-opentofu` key. Its key policy, bucket policy, and the CI role's
`terraform-state` policy have no object-ARN encryption-context restriction.

`IaC/operator/state-bucket-encryption` adopts only the existing encryption
configuration through `IaC/modules/aws-s3-bucket-encryption`. The explicit
stack generates its unit from
`IaC/.catalog/units/operator/state-bucket-encryption/terragrunt.hcl`.
The declared change enables bucket keys and preserves the default KMS ARN,
SSE-KMS, the existing SSE-C block, bucket contents, version history, and
client-side state encryption.
`prevent_destroy` guards the encryption configuration. This operator-owned
unit is applied independently of production CI.

Bucket keys apply to new writes, including writes using an explicitly chosen
KMS key. Existing versions retain their original encryption. They reduce only
S3-originated KMS requests, not OpenTofu's client-side calls or SSM requests.
August's total request charge was only $0.07, so savings at current volume are
at most pennies per month. Do not rewrite old objects just to chase this cost.
See [AWS S3 Bucket Keys](https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucket-key.html).

## Apply, verify, and rollback

Use the authenticated administrator session and the committed inputs:

```sh
cd IaC
terragrunt stack generate
cd operator/state-bucket-encryption
terragrunt --log-disable init -backend=false -no-color
terragrunt --log-disable run --no-auto-init -- validate -no-color
terragrunt --log-disable init -reconfigure -no-color
terragrunt --log-disable plan -no-color -out=plan.out
# Expect one import, one in-place encryption update, and no deletions.
terragrunt --log-disable apply -no-color plan.out
aws s3api get-bucket-encryption --region us-east-1 \
  --bucket rstuhlmuller-aws-s3-use1-datalake
terragrunt --log-disable plan -no-color
```

Verify `BucketKeyEnabled: true` and an empty follow-up plan. Inspect the next
normally written state object's `head-object` metadata for bucket key usage;
do not force a workload change just for a test. Review the next full month's
Cost Explorer usage to measure realized savings.

Rollback: change `bucket_key_enabled` to `false` in the catalog source,
regenerate, validate, plan, and apply this same unit. Keep the encryption
resource and keys. Objects already using bucket keys remain readable.

Validation and rollout status: applied September 5, 2026. One import, one
in-place update, no additions or deletions. Compared the saved plan's before
and after JSON: only `bucket_key_enabled` changed. OpenTofu validation,
repository-wide Terragrunt HCL validation/formatting, module formatting, the
repository Conftest gate, and all 56 saved-plan policy checks passed.
The follow-up live plan returned exit 0 with no changes. AWS reports bucket
keys enabled. The operator state object written during apply still omitted
`BucketKeyEnabled` in HEAD metadata, so per-object adoption and realized
request savings remain unverified; inspect subsequent normal state writes.
