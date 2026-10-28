# Platform Maintenance Etcd Version Gate

The protected Platform Maintenance workflow rechecks the exact offsite etcd
snapshot and manifest versions immediately before each Talos node upgrade and
before the Kubernetes upgrade. A stale receipt, missing version, changed
checksum, deleted version, disabled versioning, or changed bucket encryption
blocks the next mutation before its durable start marker.

The workflow first obtains a separate `oce-platform-etcd-reader` AWS profile
from the `homelab-platform-etcd-reader` OIDC role. The role trusts only the
protected `homelab-production` Platform Maintenance workflow on `main` when
the owner starts it. Its permissions boundary permits reading versioned objects
under `etcd/*` in the dedicated offsite bucket and the bucket's S3 KMS key.
`s3:GetObjectVersion` **also permits downloading raw etcd snapshots**. Keep
these credentials out of shared `Github-TF-State` and other workflows. The
shared maintenance credentials remain a separate default identity.

The reader session lasts 9,000 seconds; the maintenance job timeout is 7,200
seconds. The executor selects the named profile explicitly and verifies its
assumed-role ARN before each S3 check. It suppresses private AWS output and
uses the receipt's pinned keys, versions, SHA-256 checksums, byte counts, and
current main SHA. The gate checks stored S3 metadata and exact version
availability; the separate publisher is responsible for byte-level readback
and offline restore proof. A source change after this check remains a small
race; the next node or cluster command rechecks before proceeding.

Apply the new `operator/platform-etcd-reader` Terragrunt unit only through a
reviewed, protected plan and declared apply. A source-only PR and passing
fixtures do not establish that the role or receipt source exists in AWS. If
the reader fails or expires during an upgrade, the workflow stops. Inspect
the durable node receipt and live health, publish fresh recovery evidence at
the current main SHA when needed, then retry the protected stage. Never infer
that a started node command is safe to repeat from a failed job alone.

Validate source changes with `tofu test` in
`IaC/terragrunt-catalog/modules/aws-platform-etcd-reader`,
`python3 -I scripts/ci/platform-maintenance-test.py`,
`conftest verify --policy policy`, and the protected workflow check.
