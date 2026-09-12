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

The manual CLI remains available. The separate
[offsite attempt scheduler](../../etcd-offsite-schedule.md) adds an hourly
LaunchAgent using the same publisher and existing named AWS/SSO profile. It
shares the local snapshot lock only while verifying and retaining a private
pair, resumes that pair independently of later local retention, and deduplicates
by snapshot SHA. Freshness stays bound to the exact published manifest
`created_at`, including when a newer local capture has identical snapshot bytes.
Exact-version retrieval must succeed before offsite status can become fresh.
The scheduler never changes local backup cadence or deletes offsite copies.
Its committed 4 GiB attempt budget and 8 GiB filesystem reserve include partial
downloads and preflight the known next copy/retrieval bytes. Capacity blocks
preserve prior verified state and require operator capacity maintenance, so
retained offsite attempts cannot grow without a policy limit on the Mac's
shared backup filesystem.
Its [script](../../../scripts/etcd-offsite-schedule.py) and
[policy](../../../scripts/config/etcd-offsite-schedule.json) are synthetic-tested;
installation and real recurring execution remain unverified. Expired existing
SSO sessions require ordinary operator login; no new unattended identity is
introduced. Private status/logs do not deliver remote alerts.

Synthetic tests cover failure and recovery paths;
one real publication and exact-version retrieval completed on 2026-09-07 at
`17:55:16 UTC`, using the first scheduled snapshot. Independent checks confirmed
both remote versions/checksums and matching original, working and downloaded
bytes, including the embedded etcd checksum. The source was preserved; exact
version IDs and receipts remain private. Unattended offsite freshness remains
unverified. The downloaded snapshot has not been restored; the earlier offline
restore used a different manual post-upgrade snapshot.
Database restoration uses [[operations/etcd-offline-restore-validation]];
neither helper proves control-plane startup or PVC recovery.
