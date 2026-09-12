# Manual Etcd Offsite Publication

For recurring attempts using this publisher and an existing AWS/SSO profile,
see [Scheduled Etcd Offsite Attempts](etcd-offsite-schedule.md). The manual
commands below remain unchanged.

`scripts/etcd-offsite-backup.py` publishes one already verified local snapshot
and manifest, then downloads their exact S3 versions and repeats offline
checksum verification. It uses the
[dedicated operator bucket](etcd-offsite-storage.md), whose apply and metadata
verification must already have passed. No schedule, new AWS identity, or
unattended credential mechanism is introduced.

The account, region, and bucket come from
[one committed destination file](../IaC/config/etcd-backup-storage.json), also
consumed by the operator Terragrunt catalog. CLI options cannot choose another
bucket, account, or region. The existing administrator profile selects only
credentials. Each S3 call supplies the expected owner, and STS must confirm the
declared account before publication or retrieval. Versioning must be Enabled.

## Prepare And Publish

Keep a completed [local backup](talos-etcd-backup.md), containing
`etcd.snapshot` and `manifest.json`, outside Git. Choose an existing durable
mode-0700 directory outside Git and outside that backup for the publication
receipt, working copy, and independently downloaded copy. Every operation file
is mode 0600. Allow space for both copies and retain the original.

Use an absolute path to the installed AWS CLI v2 and an existing file-backed
profile or SSO session. The default profile is `default`; authenticate normally
before running the helper. It does not log in, create credentials, assume a new
role, or read Talos client configuration. Exported `AWS_*` credentials and
configuration selectors are ignored. Fixed regional AWS service endpoints
prevent profile endpoint settings from changing the destination; there is no
endpoint override option in this helper.

```sh
python3 scripts/etcd-offsite-backup.py \
  --aws-cli /absolute/path/to/aws --profile default publish \
  --backup-directory "/path/to/private-backups/etcd-<completed-backup>" \
  --destination /path/to/private-offsite-receipts
```

The helper first checks the embedded snapshot SHA-256 and manifest digest,
then makes a private working copy. It creates an unpredictable unique prefix
`etcd/<snapshot-sha256>/<publication-id>/` and retains `publication.json` locally
before touching S3. Only the snapshot and manifest are uploaded; no Talos
credentials or neighboring backup files are copied.
Copied files, the receipt, and its directory entries are synced before the
first AWS operation. Downloaded files and receipt/directory entries are synced
before a completed retrieval is reported; a sync failure is an operation
failure and preserves the retained data for inspection.

Publication creates `etcd.snapshot` first and `manifest.json` last. Both use
conditional `If-None-Match: *`, full SHA-256 checksums, explicit SSE-KMS with
the existing regional S3 key, and Bucket Keys. Existing different bytes cause
failure. There is no overwrite or remote-delete operation, multipart upload,
or automatic expiry. Files larger than 5 GiB are rejected by this single-object
workflow. Returned checksums, size, encryption, and immutable version IDs are
checked before the local receipt advances.

The manifest is the remote completion marker for the pair. The private receipt
binds both exact version IDs and digests. A `published` receipt means both
uploads completed; only `verified` means the independent version-specific
download also passed the existing offline snapshot verifier. Keep the receipt
as recovery metadata: downloading by recorded version avoids relying on an
object's current/latest version.

## Resume A Partial Attempt

A failed invocation retains its original, private `publication-*` working
directory, receipt, and any `.partial-retrieval-*` directories. It never deletes
cloud objects or local recovery data. Inspect the retained receipt to identify
the publication directory, then resume that exact attempt:

```sh
python3 scripts/etcd-offsite-backup.py \
  --aws-cli /absolute/path/to/aws --profile default publish \
  --backup-directory "/path/to/private-backups/etcd-<completed-backup>" \
  --destination /path/to/private-offsite-receipts \
  --resume-directory "/path/to/private-offsite-receipts/publication-<id>"
```

Resume requires the original and retained working copy to match. It checks
already recorded immutable versions. If a put succeeded but its response was
lost, the exact key is reused only after its current version's size, checksum,
and encryption match the retained bytes. A different object or missing
recorded version fails; no cleanup or overwrite is attempted. Each invocation
without `--resume-directory` creates an independent prefix and may store an
additional copy.

## Retrieve Using Recovery Metadata Only

Retrieval needs the private `publication.json` receipt and the existing AWS
session; it does not need a surviving local snapshot or manifest. Keep the
receipt in an owned mode-0700 directory with mode 0600. Select a different
durable output directory:

```sh
python3 scripts/etcd-offsite-backup.py \
  --aws-cli /absolute/path/to/aws --profile default retrieve \
  --publication-directory /path/to/private-recovery-metadata \
  --destination /path/to/private-downloads
```

Each download names the recorded version ID and asks S3 for checksum metadata.
The helper hashes downloaded bytes, verifies the embedded etcd checksum and
manifest, and records a private `retrieval.json` before publishing a unique
`retrieval-*` directory. Failed downloads remain marked `.partial-retrieval-*`.
The publication receipt must stay unchanged throughout verification.

This proves a checksummed offsite copy can be retrieved at execution time.
It does not prove control-plane startup, PVC recovery, ongoing offsite
freshness, or resilience against loss of the AWS account. Run the separately
reviewed [offline restore validator](etcd-offline-restore-validation.md) on a
downloaded copy for database restoration evidence; full recovery still needs
the control-plane runbook and separately protected Talos recovery material.

## Validation

```sh
python3 scripts/ci/etcd-offsite-backup-check.py
```

Synthetic fixtures exercise conditional creation, partial failures, lost put
responses, resume, changed local/remote bytes, private paths, wrong identities,
suspended versioning, exact-version retrieval using receipt-only recovery
metadata, and receipt changes during download. They execute no AWS operations.

On 2026-09-07, the merged helper from
[PR #1010](https://github.com/Stuhlmuller/homelab/pull/1010) completed one manual
publication and exact-version retrieval at `17:55:16 UTC`. It used the first
scheduled snapshot from `17:17:10 UTC`, containing `61,505,568` bytes. Independent
acceptance confirmed both immutable S3 versions and their checksum metadata;
the original, local working copy and downloaded snapshot matched, including
the embedded etcd checksum. The original snapshot and manifest were preserved.
Exact version IDs, digests, and execution/acceptance receipts remain private.

This proves one offsite copy and retrieval at that time. Unattended offsite
publication, ongoing freshness, control-plane recovery and PVC recovery remain
unverified. This downloaded scheduled snapshot has not undergone a database
restore; the separate successful offline restore used an earlier manual
post-upgrade snapshot.

- [AWS conditional puts and checksum arguments](https://docs.aws.amazon.com/cli/latest/reference/s3api/put-object.html)
- [AWS version-specific retrieval](https://docs.aws.amazon.com/cli/latest/reference/s3api/get-object.html)
- [AWS object metadata](https://docs.aws.amazon.com/cli/latest/reference/s3api/head-object.html)
