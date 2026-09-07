# Manual Etcd Offsite Publication

Tags: #operations #backup #storage

The [manual publication runbook](../../etcd-offsite-publication.md) and
[helper](../../../scripts/etcd-offsite-backup.py) use the deployed
[[operations/etcd-offsite-storage|dedicated bucket]]. One committed JSON
destination feeds both the operator catalog and helper; no account, region,
bucket, or endpoint override is accepted by the helper.

An existing file-backed AWS/SSO profile must match the declared account.
The helper publishes a verified private working snapshot first and manifest
last, with conditional creation and full-file checksums. A retained private
receipt records exact version IDs before an independent version-specific
download repeats the existing offline verifier. Resume preserves partial
objects and local copies and never overwrites different bytes. Receipt-only
retrieval remains possible after local snapshot loss.

This is manual offsite copy/retrieval support, not scheduled publication or
new unattended credentials. Synthetic tests cover failure and recovery paths;
actual publication/retrieval must be recorded after reviewed execution.
Database restoration uses [[operations/etcd-offline-restore-validation]];
neither helper proves control-plane startup or PVC recovery.
