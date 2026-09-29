# Monitoring reliability candidate (HOME-4)

Status: **inactive implementation, not a completed migration**. Main still uses
NFS and disables Watchdog. Nothing in `reliability-candidate/` is registered in
the active Application. No hardware, receiver account, live backup, or rollout
is authorized. Keep HOME-4 in review through operational acceptance.

## Evidence and storage decision

Revalidated source at `32dc911c` on 2026-09-29. PR #973 was merged as a design,
not a migration implementation. Preserve its all-writer fencing and rollback
requirements. This workspace has no kubectl, Talos client, or configured cluster
access; **no fresh hardware/capacity or production state was measured**.

Choose a dedicated, healthy **local ext4 filesystem** for both Prometheus and
Alertmanager, with static `local` PVs, `Retain`, node affinity and
`WaitForFirstConsumer`. This removes both consumers' NAS dependency without
introducing a distributed storage control plane. The candidate class is
`monitoring-local`; it does not replace `nfs-default`. It deliberately uses
`local`, not `DirectoryOrCreate` hostPath: a missing mount must not silently
become another directory on the system disk.

This selects a storage architecture, **not a verified node/device**. The node
sentinel cannot match a real Kubernetes node. Before activation, select a
verified dedicated device and add its reviewed Talos UserVolume/mount and
directory ownership declarations. No partitioning, hardware purchase or Acer
fallback is included. The September 6 observations found ~32 GB worker eMMC,
no spare data device, and insufficient worker disk headroom; Acer alone had
space but an unresolved integrity incident. September 12 QNAP research found
an iSCSI option requiring driver/extension/credential work, still sharing the
NAS failure domain. That option does not satisfy this candidate's independence
objective. See the [existing evidence](knowledge-base/operations/qnap-monitoring-block-storage-research-2026-09-12.md)
and [migration design](knowledge-base/operations/monitoring-storage-migration-draft-2026-09-06.md).

| Budget | Requirement |
| --- | --- |
| Prometheus | Preserve 50 GiB and 15 days; no new size retention cutoff |
| Alertmanager | Preserve 10 GiB and 120 hours |
| Checkpoint and restore scratch | Two additional measured complete dataset copies, outside old claims |
| Free filesystem reserve | At least 20% after the above reservations, plus measured replay/compaction peak |
| Historical sizing only | ~8 GiB Prometheus and ~8 KiB Alertmanager on September 6; remeasure |
| Example lower bound | `(60 + 2 * 8) / 0.8 = 95 GiB`; not a disk purchase specification |
| Scheduling | Preserve 1536 MiB Prometheus and chart 200 MiB Alertmanager requests; measure cold replay and eligible-node spare RAM |

PV sizes do not impose per-directory quotas on the shared local filesystem.
Record actual device identity, ext4 mount, free bytes, growth, memory and
compaction/replay peak. Reject unsupported or unhealthy backing. No automatic
failover is possible: loss of the selected node stops both local consumers;
data needs recovery on healthy hardware. Acer loss also removes the sole
control plane. An independent heartbeat reports monitoring loss even when
cluster alerting cannot run. This is not high availability.

## Delivered code and remaining implementation gates

- `reliability-candidate/storage.yaml`: distinct retained PV/PVC pairs; names
  match Operator/Helm claim naming, old claims remain untouched.
- `fence-*.yaml`: one workload at zero replicas, unpaused, explicit retention.
- `target-*.yaml`: new templates and node affinity, still zero replicas.
- `scripts/monitoring-checkpoint.py`: complete cold-directory copies (including
  WAL/head and silence/notification state), file hashes, before/after source
  comparison, fsync and atomic publication; refuses symlinks, hard links,
  special files, overlaps, reused claims and existing destinations. Failed
  `.partial` directories and locks are retained for private diagnosis.
- Restore requires manifest-bound application-restore and independent-retrieval
  evidence and an identical application image identity. These are **trusted
  operator attestations**, not automatically measured facts. It publishes a
  receipt explicitly setting `startup_authorized: false`.

The committed plan has null claim identities and no collector. **Production
copying and startup remain blocked**. Complete these code gates in an activation
PR after placement/access is known: Talos volume provisioning, a reviewed live
fence collector, bounded copy/verification Job or operator-host mount wiring,
and a runtime startup guard which rechecks fencing after scheduler delay.
There is intentionally no replicas-one overlay, mounted production Job or
unsafe marker-only init container. The copy helper is not a live orchestration
system; do not remove these gates merely because its synthetic tests pass.

The collector is an absolute executable plus arguments, pinned by SHA-256 in
the private plan. The helper appends `checkpoint|restore` and the canonical
plan hash, invokes it with a 20-second timeout before copying, during copying,
and before publishing, and discards private diagnostics. It must read current
Kubernetes **and authenticated node/runtime state**, not replay a JSON file.
The mount-wiring contract must identify this operation's sole authorized copy
consumer; exclude only its exact UID from prior-writer/mount absence checks,
and reject any other consumer. No collector is approved until this identity
check and lease lifetime are exercised under node loss and cancellation.
Its JSON response contract is:

```json
{
  "plan_sha256": "hash supplied to the collector",
  "phase": "checkpoint",
  "observed_at": 0,
  "all_consumers_accounted": true,
  "controllers_zero": true,
  "writer_pods_absent": true,
  "nodes": [{
    "name": "selected-node", "boot_id": "observed-boot-id",
    "healthy": true, "writers_absent": true, "writable_mounts_absent": true
  }]
}
```

Require all inventoried former production/copy/restore nodes, exact claim/PV
UIDs and CR generations, controller zero state, absent Pods including
terminating Pods, and node-side process/writable-mount absence. Evidence older
than 30 seconds, unknown consumers, unhealthy nodes and boot changes fail.
Kubernetes Pod absence and RWO alone never fence a writer. This implementation
rejects unreachable nodes; a held power-off/reset path requires a separate
reviewed collector protocol. Keep source mounts read-only and sources/checkpoint
trees private and inaccessible to other writers for the entire operation;
hash comparison is not a substitute for that fence or an adversarial sandbox.

## Reviewed rollout sequence (separate approvals, one workload at a time)

1. Record current main, exact Helm/Operator/images, all old PVC/PV UIDs,
   StatefulSet/CR generations, all possible writer nodes/boot/container IDs,
   historical query/time range and Alertmanager silence invariants. Verify
   healthy target and reserve budgets. Obtain accepted interruption/RPO/RTO.
   Preserve original claim/PV identities in git with `Prune=false,Delete=false`
   and `Retain`; never change an already bound claim's storage class.
2. Approve the receiver separately and prove missing-heartbeat notification
   before storage downtime, or arrange independent human monitoring throughout.
3. Commit only the selected workload's `fence-*.yaml` as an extra chart value
   file in the Application's existing Helm source. Reconcile through the
   approved GitOps path, keeping `paused: false`. Observe zero desired/actual
   replicas and the complete node fence. Preserve 600s Prometheus/120s
   Alertmanager termination grace. Do not scale both down together by default.
4. Run the reviewed helper through the declared, approved mount/Job path.
   `--source` is the *application data directory*, e.g. old claim's
   `prometheus-db`, not its parent. `--destination` is a new private checkpoint
   directory on independent storage. A private plan based on
   `scripts/config/monitoring-migration.json` must contain actual immutable IDs,
   the exact image digest and pinned collector. Example interface only:

   ```sh
   python3 scripts/monitoring-checkpoint.py checkpoint \
     --plan /private/monitoring/plan.json \
     --source /private/monitoring/source/prometheus-db \
     --destination /private/monitoring/checkpoints/unique-operation
   ```

5. Independently publish and retrieve the complete `data/` plus `manifest.json`
   set and verify every byte before approving restore proof. HOME-2 PR #1113's
   current publisher contracts do **not** yet accept monitoring directories;
   add a monitoring adapter and exact prefix permissions in that owner's
   integration revision, or approve an existing independent destination.
   Neither an on-NAS copy nor a locally written proof Boolean is independent
   retrieval. Do not enable the admin snapshot API casually; recurring live
   Prometheus backups require the restricted snapshot route, not a live file
   copy. Recurring backup publication remains an activation prerequisite.
6. Restore a scratch copy and run the exact application image without production
   credentials, scrapes, remote writes, rules or notification receivers. Require
   HOME-3's enforced offline boundary before processing real archives. Prove
   WAL/block replay, representative historical queries/time range, and preserved
   silence/notification state; stop cleanly. Store receipts privately. Failed
   proof leaves the original writer fenced and every original copy retained.
7. Commit that workload's `target-*.yaml` and verified PV declarations while
   still at zero replicas. Confirm the operator-recreated StatefulSet uses the
   new claim. Repeat live fences; restore into the previously absent target
   application subdirectory:

   ```sh
   python3 scripts/monitoring-checkpoint.py restore \
     --plan /private/monitoring/plan.json \
     --source /private/monitoring/checkpoints/unique-operation \
     --destination /private/monitoring/target/prometheus-db \
     --proof /private/monitoring/restore-proof.json
   ```

   The helper creates files as the executing UID, mode governed by umask 077.
   Production mount wiring must run it as UID 1000/GID 2000 or normalize and
   verify ownership under a separately declared Job while fenced. It performs
   no recursive chown itself. Never use a preexisting application directory.
8. Once the actual-startup live fence guard is implemented and tested, approve
   a reviewed replicas-one revision. At actual start revalidate both source and
   restore writers, exact restored digest/target UID and healthy backing. Only
   then permit one writer. Verify ingestion, historical queries, healthy rule
   evaluation, target coverage, Alertmanager silences and normal Discord delivery.
   Exercise a controlled restart with all those checks repeated. Then migrate
   the other workload. A Ready Pod alone is insufficient.
9. Retain old claims and checkpoints through at least one full 15-day retention
   window and a new independent backup/restore cycle. Measure achieved RPO/RTO.
   Cleanup/startup-guard retirement requires another reviewed change restoring
   the normal one-apply bootstrap path. No deletion is part of this candidate.

## Rollback

Before new writes, fence the replacement, recheck source checkpoint identity,
and commit the original template/class with replicas zero. Revalidate the live
startup fence before allowing the old writer. After new writes, never simply
revert Helm values: NFS data is stale. Fence the new writer, create and prove
a fresh complete checkpoint, then restore into a **third, newly named retained
claim** using a new plan/operation ID. Change the template while at zero, then
perform the same actual-startup gate. Never overwrite either earlier copy.

An unreachable local node blocks lossless rollback. Require an explicit
accepted data-loss/RPO decision and proven fencing before any stale-copy
recovery. NFS rollback restores the original unsupported-storage risk; it does
not satisfy HOME-4. Failed copies retain partial directories/locks; select a
new operation path after diagnosis, rather than deleting or resuming blindly.

## Independent heartbeat and recovery coordination

The staged ExternalSecret preserves Discord configuration and sends only
`Watchdog` to an independent HTTPS webhook every minute. The Watchdog route
terminates matching, so it does not flood Discord. `send_resolved: false`
prevents a resolved event from falsely resetting the external timer. Redirects
are disabled; TLS verification stays enabled. No in-cluster cron loop substitutes
for Prometheus evaluation and Alertmanager delivery.

Preferred option: reuse an existing approved hosted dead-man receiver accepting
Alertmanager POSTs. No such account was established by repository evidence.
Concrete fallback: an owner-approved Healthchecks.io check, period 60 seconds,
grace 240 seconds, success URL in SSM `/homelab/monitoring/heartbeat-url`, and
an independent email/push recipient. Its [ping API](https://healthchecks.io/docs/http_api/)
accepts POST bodies. The service can return HTTP 200 for unknown/rate-limited
checks, so require receiver-side recorded pings and an actual missed-ping
notification, not just HTTP success. No account, check, paid plan or permission
was created. An already approved externally hosted equivalent is also suitable.
Do not self-host this receiver on the homelab or QNAP.

Activation: approve the endpoint/account/contact and any cost; apply the exact
SSM entry in `heartbeat-ssm.hcl.example` through the existing parameter module,
publish its secret value through the approved secret workflow, and verify the
ExternalSecret is Ready. Then register only the heartbeat ExternalSecret and
add `heartbeat-values.yaml` to the Helm source. **Do not register the whole
candidate directory as a shortcut.** The `.invalid` backup target and storage
sentinel are intentionally unresolved. Secret rotation under `OnChange` needs
a reviewed ExternalSecret metadata revision, as with current Discord rotation.

With approval, observe at least ten consecutive receiver pings; disable only
Watchdog via a committed temporary values revision for more than five minutes.
Confirm the independent recipient receives outage notification without
Prometheus/Alertmanager/Grafana intervention, then restore the rule and confirm
recovery. Record actual detection time. Keep external maintenance windows
bounded. Heartbeat rollback restores the prior secret selector and disabled
Watchdog together, and explicitly records loss of outage detection.

HOME-3 traffic: monitoring Prometheus needs DNS and the approved operator TLS
metrics endpoint; Alertmanager needs DNS, HTTPS to the chosen heartbeat host
and existing Discord, plus existing internal alert/Grafana flows. HOME-2 must
serve its atomic textfile metrics on the approved operator exporter. The staged
`backup-scrape.yaml` uses the chart's `release: prometheus` ScrapeConfig selector,
keeps the `homelab_application_backup_*` family and alerts on scrape failure or
absence. Integrate HOME-2's freshness rule, without duplicating it. Agree the
exact operator hostname, port, CA/auth and network policy before replacing
`backup-operator.invalid:9100`; exporter installation is not included here.

## Local validation

```sh
python3 -I scripts/ci/monitoring-checkpoint-test.py
python3 scripts/ci/monitoring-render-check.py --chart /path/to/kube-prometheus-stack
python3 -I scripts/ci/monitoring-replay-test.py \
  --prometheus /path/to/prometheus --alertmanager /path/to/alertmanager
git diff --check
```

Use chart 85.2.0, Prometheus 3.11.3 and Alertmanager 0.32.1. Render validation
checks native rule/config/routing behavior and claim names. Replay validation
uses only disposable synthetic state, loopback endpoints, no production data
or external receivers, and collects/stops every subprocess before exit.
Synthetic backup retrieval and fence attestations are mocked in replay tests;
these tests do not prove a production collector, independent backup or live
containment. Full Nix, live server-side dry runs and operational acceptance must
be recorded separately.

Upstream: [Prometheus storage](https://prometheus.io/docs/prometheus/latest/storage/),
[local volume scheduling](https://kubernetes.io/docs/concepts/storage/volumes/#local),
[Alertmanager configuration](https://prometheus.io/docs/alerting/latest/configuration/).
