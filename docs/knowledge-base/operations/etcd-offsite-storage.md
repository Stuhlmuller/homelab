# Etcd Offsite Storage

Tags: #operations #storage #backup

The [operator runbook](../../etcd-offsite-storage.md) declares the dedicated
`homelab-etcd-backups-716182248480-us-east-1` S3 bucket through
`IaC/operator/etcd-backup-storage`. The reusable
[module](../../../IaC/modules/aws-backup-bucket/main.tf) owns its complete bucket
configuration; the [catalog unit](../../../IaC/.catalog/units/operator/etcd-backup-storage/terragrunt.hcl)
pins the account and region and shares the normal encrypted state backend.

Versioning retains completed object versions indefinitely. The only lifecycle
action aborts incomplete multipart uploads after seven days. Owner-enforced
ACLs, public-access blocks, TLS, SSE-KMS with the existing regional AWS-managed
S3 key, and bucket destruction guards are declared. No new IAM policy or KMS
key is required. This is separate from the existing state bucket's lifecycle
and encryption-only ownership.

Generic CI performs offline validation but does not live-plan or apply operator
units. An existing administrator session must review and apply a focused saved
plan. Module tests reject an unexpected account, region, and bucket-name suffix.

This storage declaration does not establish an offsite backup: publication,
version-specific retrieval with offline verification, unattended credentials,
freshness monitoring, retention objectives, and an isolated restore drill
remain separate work. Record an actual apply and verified copy before marking
either ready. See [[architecture/storage-and-state]] and
[[operations/kubernetes-patch-maintenance-2026-09]] for local recovery evidence.
