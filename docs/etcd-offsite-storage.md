# Dedicated Etcd Offsite Storage

`IaC/operator/etcd-backup-storage` declares a dedicated S3 bucket for verified
etcd snapshots. It uses the existing AWS account and shared encrypted state
backend, while owning its bucket independently of the backend bucket's objects
and lifecycle rules. The unit declares storage only. The separate
[manual publisher/retriever](etcd-offsite-publication.md) copies verified
snapshots; a schedule, unattended AWS identity, restore drill, or completed
offsite copy is not implied by a successful bucket apply.

## Ownership And Retention

These are this homelab's public deployment values. Other deployments must change
the [committed destination](../IaC/config/etcd-backup-storage.json), consumed by
both the catalog inputs/provider guard and manual publisher.

| Setting | Declared value |
| --- | --- |
| Owner account | `716182248480` |
| Region | `us-east-1` |
| Bucket | `homelab-etcd-backups-716182248480-us-east-1` |
| State key | `IaC/homelab/operator/etcd-backup-storage/terraform.tfstate` |
| Encryption | SSE-KMS, existing regional `alias/aws/s3`, S3 Bucket Keys |
| Object ownership | `BucketOwnerEnforced`; ACLs disabled |
| Public access | All four S3 public-access blocks enabled; TLS required |
| Retention | Versioning enabled; no current or noncurrent object expiration |
| Incomplete uploads | Abort multipart uploads after seven days |

`force_destroy = false` and `prevent_destroy = true` protect the bucket against
ordinary destructive OpenTofu plans. These are not Object Lock or protection
against removing the resource declaration or deleting objects outside this
workflow. Keep the module and state ownership intact. Object expiration,
replication, a log destination, and recovery objectives require a later reviewed
decision. Incomplete-upload cleanup removes unfinished parts, not completed
snapshot versions.

Read-only metadata on 2026-09-07 confirmed the existing shared backend bucket
has versioning and SSE-KMS, with expiration scoped to `Tailscale/`. That rule
does not currently overlap a separate backup prefix. A dedicated bucket gives
this repository complete ownership of backup retention and avoids coupling
recovery artifacts to future lifecycle changes in the shared bucket. Existing
CI permissions already include S3 management; this unit adds no IAM grants.

## Validate And Plan The Operator Unit

The catalog is the source of truth. Generate the unit from the repository root
and validate without opening remote state:

```sh
nix develop
cd IaC
terragrunt stack generate
cd operator/etcd-backup-storage
terragrunt --log-disable init -backend=false -lockfile=readonly -no-color
terragrunt --log-disable run --no-auto-init -- validate -no-color
terragrunt --log-disable run --no-auto-init -- test -no-color
```

Tests use dummy credentials and override identity reads. They reject the wrong
account, region, or shared bucket name, and check retention and private storage
controls without accessing AWS. The normal static gate runs these tests. The
GitHub plan/apply workflows **do not traverse `IaC/operator`**: green generic CI
is not a live plan or deployment receipt for this bucket.

Use the existing administrator session through the default AWS credential
chain. Desired-state values come from the committed catalog and destination
JSON; do not export profile or infrastructure overrides for this workflow.
If the default session is not
the intended administrator, stop and select the normal local authenticated
context before continuing. The AWS provider also rejects any account other than
the declared owner. From the same unit directory:

```sh
set -euo pipefail
umask 077
aws sts get-caller-identity --output json |
  jq -e '.Account == "716182248480"'
backup_plan_dir="$(mktemp -d /tmp/homelab-etcd-bucket-plan.XXXXXX)"
chmod 0700 "$backup_plan_dir"
terragrunt --log-disable run --download-dir "$backup_plan_dir/cache" \
  --disable-bucket-update --backend-bootstrap=false -- \
  init -reconfigure -lockfile=readonly -no-color
terragrunt --log-disable run --download-dir "$backup_plan_dir/cache" \
  --disable-bucket-update --backend-bootstrap=false -- \
  plan -input=false -lock-timeout=5m \
  -out="$backup_plan_dir/etcd-bucket.tfplan" -no-color
terragrunt --log-disable run --download-dir "$backup_plan_dir/cache" \
  --no-auto-init -- show -json "$backup_plan_dir/etcd-bucket.tfplan" \
  >"$backup_plan_dir/etcd-bucket.json"
terragrunt --log-disable run --download-dir "$backup_plan_dir/cache" \
  --no-auto-init -- show -no-color "$backup_plan_dir/etcd-bucket.tfplan"
```

The explicit backend flags prevent Terragrunt from creating or updating the
shared state bucket. Do not opt into backend bootstrapping for this unit; its
backend already exists under separate ownership.
The private download directory also keeps generated backend metadata outside
the checkout; the repository artifact gate rejects local state files even in
ignored Terragrunt caches. Use this same directory for every live command.

Keep plan files private and outside Git. Review the saved plan before applying
it. Initial deployment should create exactly seven managed S3 resources in the
dedicated bucket: bucket, ownership controls, public-access block, versioning,
encryption configuration, TLS policy, and multipart-only lifecycle. It must not
import or change the shared backend bucket, IAM, KMS keys, existing objects, or
cluster resources. A name collision is a failure to investigate, not permission
to import another bucket. Stop on unexpected changes or credential errors.

## Apply And Verify

After the focused saved plan has passed review, apply those exact bytes from the
same unit and shell:

```sh
terragrunt --log-disable run --download-dir "$backup_plan_dir/cache" \
  --disable-bucket-update --backend-bootstrap=false -- \
  apply -input=false -lock-timeout=5m -no-color "$backup_plan_dir/etcd-bucket.tfplan"
terragrunt --log-disable run --download-dir "$backup_plan_dir/cache" \
  --no-auto-init -- output -json
terragrunt --log-disable run --download-dir "$backup_plan_dir/cache" \
  --disable-bucket-update --backend-bootstrap=false -- \
  plan -input=false -lock-timeout=5m -detailed-exitcode -no-color
```

The final plan must exit zero with no changes. Verify the bucket's location,
encryption, versioning, ownership, public-access settings, TLS policy, and sole
incomplete-upload lifecycle rule using read-only AWS metadata calls with
`--region us-east-1` and `--expected-bucket-owner 716182248480` where supported.
Retain the private plan and verification receipt in the operator's durable
maintenance directory. Do not treat creation alone as backup readiness.

On 2026-09-07, the merged unit from
[PR #1008](https://github.com/Stuhlmuller/homelab/pull/1008) applied the reviewed
saved plan once, from `17:34:28` through `17:35:38 UTC`: seven resources added,
none changed or destroyed. Read-only bucket metadata acceptance passed;
provider refresh and the follow-up no-drift plan exited zero at `17:37:27 UTC`.
That provider check also covered the SSE-C block field absent from the
installed AWS CLI model. Private receipts retain the exact plan and source
identity. No snapshot objects were uploaded by this storage acceptance.

The [manual publisher/retriever](etcd-offsite-publication.md) publishes an
already verified local snapshot and manifest, then retrieves their immutable
object versions and repeats offline verification. Its first manual execution
passed on 2026-09-07, after bucket acceptance. Keep local copies and the private
version receipt. The bucket unit does not run this workflow or supply unattended
credentials; ongoing offsite freshness and full recovery remain separate gates.

Rollback is a reviewed forward correction to bucket configuration. Do not
destroy the bucket, suspend versioning, or add expiration to undo this unit.
Preserve stored versions and state while investigating an incomplete apply.

## Sources

- [Bucket module](../IaC/modules/aws-backup-bucket/main.tf)
- [Catalog unit](../IaC/.catalog/units/operator/etcd-backup-storage/terragrunt.hcl)
- [Operator ownership](../IaC/operator/README.md)
- [Local etcd verification](talos-etcd-backup.md)
- [AWS lifecycle rule scope](https://docs.aws.amazon.com/AmazonS3/latest/userguide/intro-lifecycle-rules.html)
- [AWS incomplete-upload cleanup](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpu-abort-incomplete-mpu-lifecycle-config.html)
