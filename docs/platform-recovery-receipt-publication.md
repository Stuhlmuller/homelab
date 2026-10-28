# Platform recovery receipt publication

The [operator-LAN candidate producer](../scripts/platform-recovery-candidate.py)
captures direct authenticated Talos access and restores a downloaded etcd
snapshot offline on the operator Mac. Its private `stage` operation writes three
non-authoritative, checksummed objects to the dedicated etcd backup bucket under
`platform-candidates/<exact-main-sha>/<random-id>/`. The local `staging.json`
records each exact key, S3 version ID, byte count, and SHA-256. Keep that file,
the candidate JSON, the Talosconfig, and all downloaded backup copies private.

The [protected publisher workflow](../.github/workflows/platform-recovery-receipt-publication.yml)
accepts only the exact current main SHA, the opaque staging ID, and the three
SHA-256 digests privately reviewed against `staging.json`. Do not pass JSON,
Talos diagnostics, version IDs, or credential material in dispatch inputs. The
production environment approval attests the direct-LAN candidate's origin;
GitHub-hosted CI cannot itself witness the Mac's physical route.

Before publication, the workflow checks the owner actor, first attempt, exact
main, pinned script hash, and dedicated OIDC role. The script requires a clean
checkout and the protected main remote, then reads one current, undeleted S3
version of each staged object. It checks the reviewed digests, candidate shape,
freshness, direct-LAN fields, and downloaded exact-version snapshot/manifest and
offline-restore receipt linkage. It checks main, source versions, and the live
application bucket policy again before each conditional, KMS-encrypted write.
The application backup bucket policy
permits only `homelab-platform-receipt-publisher` to write the four fixed
platform prerequisite keys and denies their deletion. The script writes and
reads back only `direct-recovery.json` and `off-node-etcd-backup.json` for the
current SHA. A separately reviewed producer must create measured `placement`
and `artifact-publication` receipts.

The operator must first review and apply the `application-backup-storage` plan
through the declared protected IaC workflow, confirm the dedicated role and
bucket policy, then run the publisher only after the producer branch and this
workflow have merged with clean protected checks. No role apply, candidate
stage, publisher dispatch, or platform upgrade is implied by this source.

If main advances or a candidate expires, capture and stage new evidence on
the new exact main. A failure after the first receipt write may leave that
single immutable receipt under the old SHA. Never delete or overwrite it to
force a retry. A new SHA and fresh capture are required if its six-hour window
expires. The bucket is versioned and uses conditional writes; it has no Object
Lock, and a privileged account administrator could change the bucket policy.

These two receipts do not establish a bootable control-plane rebuild, Talos
machine-config and cluster-secret recovery, an isolated canary, artifact
publication, or a safe upgrade. T023 stays open until all four prerequisite
receipts, source-object availability at stage time, scoped plans, and direct
recovery have independent evidence. Keep platform activation disabled.
