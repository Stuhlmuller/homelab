# Renovate runtime reliability investigation

Status: two scheduled local-cache runs passed; this change retires timing remaps.
This record covers the hourly full dry runs. It does not close writer cutover,
cache-capacity recovery, policy parity, or seven-day migration acceptance.

## October 29 baseline

All times are UTC on 2026-10-29. The runner used Renovate 44.167.4, the shared
`nfs-default` cache claim, ephemeral clones, and a 2,400-second Job deadline.
All observed Pods used these same runtime settings.

Five consecutive 16:00–20:00 Jobs failed with `DeadlineExceeded`. Their deleted
Pods' terminal logs were unavailable. All five exact CRI container-log
directories were absent on `zimaboard-0`; no supported central Kubernetes log
retention route was found. Other possible copies were not exhaustively searched.
Historical metrics establish the Pod and Job identities and deadline outcomes,
not terminal repository coverage or the presence of mutex errors in those runs.

| Scheduled run | Mean CPU, cores | Throttled CFS periods | Container I/O PSI full |
| --- | ---: | ---: | ---: |
| 16:00, failed | 0.418 | 0.48% | 20.96% |
| 17:00, failed | 0.432 | 0.38% | 22.33% |
| 18:00, failed | 0.423 | 0.33% | 22.48% |
| 19:00, failed | 0.307 | 0.69% | 41.49% |
| 20:00, failed | 0.407 | 0.83% | 30.77% |
| 23:00, successful | 0.576 | 2.52% | 12.73% |

The five failed-run windows cover each scheduled slot's first 40 minutes, not
proven container lifetimes. The 23:00 row covers its 1,791-second container
lifetime, with 1,776.324 seconds observed. Identities were checked against
`kube_pod_info`, Job-owner
UIDs, and matching container cgroups. Counter resets were absent; the largest
historical scrape gap was 50.387 seconds. Higher container I/O pressure correlates
with failure; it does not identify NFS or a mutex holder as the cause.

The 21:00, 22:00, and 23:00 scheduled Pods each completed all nine repositories
with zero repository and process exit codes, 122 dry-run markers, and no
`ERROR`, `FATAL`, or mutex markers. They still spent 506.654, 405.609, and
338.677 seconds after the final repository, respectively. These baseline
successes do not establish a fix for the intermittent failures.

The 23:00 Pod (`c7aa0e54-2c63-4287-88d7-583128b056fa`) ran from 23:00:02 to
23:29:53; its Job completed at 23:29:57. The first repository reached dependency
extraction completion in 48.359 seconds, then took another 556.038 seconds to
its first dry-run action and 280.553 seconds to repository completion. This
locates most of that repository's delay after extraction, without separating
cache access, upstream requests, or later processing.

During the final 338.677 seconds, mean CPU was 0.425 cores, throttled CFS periods
were 8.67%, and I/O PSI some/full were 11.98%/9.34%. The repository phase had
13.95%/13.56% I/O PSI. CFS throttling divides throttled periods by observed
periods; PSI divides pressure-counter growth by observed elapsed time. These
different denominators cannot establish relative CPU/I/O cost or I/O dominance.
Finalization had 23 samples spanning
319.920 seconds; a 14.328-second scrape interval straddled the phase boundary
and was excluded from both phase deltas. Throttled CPU seconds were unavailable.

Each successful run also retained two warning blocks: one advisory internal-host
notice and three digest-resolution warnings for the public declarations of
`homelab-nofx-backend`, `homelab-nofx-frontend`, and `homelab-oce-controller` in
Harbor's private project. The runner has no registry credential. Authorization
is a plausible explanation, but the warnings do not distinguish denial from
missing manifests or another lookup failure. Treat these as a separate lookup
contract finding; do not call these scans completely clean.

## Diagnostic boundary

[PR #1648](https://github.com/Stuhlmuller/homelab/pull/1648) merged as signed
commit `039ec31c8912169a591054f60bb2f7de337834f7` after all seven required checks
passed. Argo CD reconciled it at 23:15:04 and was Synced/Healthy. The live
`renovate-config-b44d5bbd6g` ConfigMap exactly matched the reviewed source, with
four cache-timing remaps and full dry-run mode. The already-running 23:00 Pod
retained its earlier configuration; it is not an instrumented run.

The [pinned cache implementation](https://github.com/renovatebot/renovate/blob/44.167.4/lib/util/cache/package/impl/file.ts)
enumerates all cache index entries, removes expired entries, and runs content
verification at finalization.
The [cache mutex wrapper](https://github.com/renovatebot/renovate/blob/44.167.4/lib/util/cache/package/with-cache.ts)
holds its lock across cache reads, upstream work, and cache writes. A waiter
timeout alone cannot distinguish those phases. Completed package-operation
statistics also cannot reveal an operation that never completed.

Node NFS counters cannot isolate this cache: six mount sources share the same
superblock and identical operation counters. Do not present their latency as
Renovate-only measurements. An [upstream comparison through 44.198.0](https://github.com/renovatebot/renovate/compare/44.167.4...44.198.0) found the
file backend, mutex wrapper, mutex implementation, and backend selection
unchanged; no targeted version fix was identified.

## October 30 instrumented NFS baseline

The 00:00 scheduled Pod (`68d86a7a-caac-4c30-87f2-12de48187468`) used the
reviewed diagnostic config and unchanged image on `zimaboard-0`. All nine
repositories finished with zero repository exit codes by 00:19:21.970. The
first repository took 866.667 seconds. It recorded these completed file-backend
operations:

| Operation | Count | Median | Maximum | Sum of durations |
| --- | ---: | ---: | ---: | ---: |
| Get | 740 | 954 ms | 37,447 ms | 1,903.437 s |
| Set | 506 | 1,684 ms | 37,109 ms | 2,587.776 s |

These are backend-call durations, including encoding/decoding, filesystem work,
and scheduling delays. They do not isolate NFS latency. Concurrent operations
overlap, so their sum is not exclusive wall time or CPU time. In-memory hits
and deduplicated callers bypass these timers; pending/rejected wrappers are
omitted, while internally caught backend failures can still count. Mutex wait
and the upstream callback are outside the timers. Maxima below 120 seconds do
not rule out mutex contention across a read, callback, and write held together.

Cleanup started at 00:19:22.006, only 36 ms after the final repository, and
ended at 00:28:00.462. The reported cleanup took 518.455 seconds, of which
content verification took 496.795 seconds (95.8%). The expiry sweep deleted
57 of 1,136 index entries; verification retained 1,061 contents totaling
6,165,858 bytes and removed 509 totaling 2,727,394 bytes. The final repository
to container-exit interval was 519.030 seconds; the container exited zero.
These markers locate the long finalization in the file-cache path rather than
an unobserved delay before cleanup. They still do not isolate filesystem,
CPU, or scheduling cost inside verification.
The Pod reached `Succeeded`, with nine zero repository exits, 122 dry-run
markers, no `ERROR`/`FATAL` or mutex markers, and the same two warning blocks
described above. This remains an NFS baseline, not local-cache acceptance.

The 01:00 Pod (`51312b53-82fd-4126-9cac-d3dcfb6ee859`) also retained the
NFS configuration. It completed all nine repositories and exited zero, with
122 dry-run markers, no error or mutex markers, and the same two warning
blocks. Its first repository took 834.818 seconds. Cleanup took 415.454
seconds, including 406.081 seconds of content verification (97.7%). The
expiry sweep deleted 47 of 1,136 entries; verification retained 1,070 contents
totaling 6,173,986 bytes and removed 562 totaling 3,980,026 bytes. This is a
second instrumented baseline, not evidence of the deployed local-cache change.

## Delivered change and acceptance

The complete rebuildable cache now targets `renovate-cache-local`, a retained
static claim on `acer`, keeping the existing NFS claim declared. New Pods
use local storage for backend operations and cleanup, preserving Renovate's
file-cache semantics without introducing Redis persistence.
The image, resource limits, schedule, full dry-run mode, 2,400-second deadline,
repository/private caching, and default TTLs remain unchanged. The initializer
changes only mount-root ownership/mode and accepts populated caches.

The 20 GiB local capacity is advisory, with no quota or node failover. It does
not satisfy dedicated capacity or recovery acceptance. Preserve the staged NAS
resources and all migration gates. The runtime evidence supports testing this
storage change, not a claim that NFS alone caused the earlier mutex failures.

Acceptance checks covered both Argo Applications, exact PV/PVC binding, the
initializer/main security contexts, and repeated distinct scheduled Pods
completing all nine repositories and cleanup without errors or mutex markers
within the unchanged deadline. Numeric cache/cleanup timings are compared below.
Faster completion and persistent binding do not prove same-key datasource
reuse or normal refresh; those migration acceptance claims remain separate.
Keep raw logs restricted. Remove temporary timing remaps through reviewed
GitOps after the comparison receipt and before enabling writes.

[PR #1755](https://github.com/Stuhlmuller/homelab/pull/1755) merged at
2026-10-30 01:11:30 UTC as signed commit
`31f679bbde838cf8fc669bd690f35f8177d0811f`. All seven required checks passed
on reviewed head `ceb88c5a4c4e4c8889d33594ed0a27837245d85c`; GitHub verified
both introduced commits and the squash signature. The merge has sole parent
`039ec31c8912169a591054f60bb2f7de337834f7`, matches the reviewed tree exactly,
and is reachable from `main`. The optional Harbor runtime audit still failed
its unchanged remediation gate; this was not treated as a passing check.

Platform storage's sync operation finished at 01:14:52 and Renovate's at
01:17:09. Both Applications reported Synced/Healthy with successful operations
at that exact merge. A read-only snapshot passed 25 delivery checks: pinned
images and both ConfigMap hashes, CronJob identity/schedule/deadline/resources,
initializer and main security/mounts, registry alias, explicit retained storage
binding, and ExternalSecret readiness. No Secret values were read.

| Resource | Verified UID |
| --- | --- |
| Existing CronJob | `35493897-3245-458f-b690-bc58fbfaab9c` |
| New local PV | `a2ab06ec-6912-48df-94fb-0eebc56cd89f` |
| New local PVC | `b9394d61-dfed-4c29-a56c-345b99c786cc` |
| Retained NFS PVC | `6e21cd25-89e9-4d1e-aee8-ef1f2519df8a` |

The old claim's UID matched a pre-rollout snapshot and remained Bound. The
already-running 01:00 Job retained its NFS claim; it cannot count as local-cache
acceptance.

## Scheduled local-cache verification

The 02:00 Pod (`a49bb062-e5cc-445a-abec-cf600d051a2f`) ran on `acer`, using
the local PV/PVC identities above and both reviewed ConfigMap hashes. Its
initializer exited zero at 02:00:01; the main container remained UID 12021 and
ran from 02:00:02 to 02:05:06 with no restart. All nine repositories finished
with zero repository exits; the process exited zero and the Pod succeeded.
The Job reported `Complete=True` at 02:05:08, well within its deadline.
It recorded 122 dry-run markers, no error or mutex markers, and the same two
warning blocks.

The distinct 03:00 Pod (`a875b996-4a81-4510-948a-4d8ec16c96ae`) used the
same local PV/PVC, node, image, and ConfigMap hashes. Its initializer exited
zero at 03:00:02 against the populated cache. The main container ran from
03:00:03 to 03:04:30, with zero exit code and no restart; its Job reported
`Complete=True` at 03:04:32. All nine repositories again exited zero, with
122 dry-run markers, no error or mutex markers, and the same warning blocks.
The two scheduled runs did not overlap.

Independent numeric audits matched all nine repositories in each run's logged
post-filter discovery list to exactly one ordered start and zero-exit finish,
with no missing, unexpected, duplicate, or untagged events. This validates
each run's discovered list, not the broader GitHub inventory.

| October 30 run | Cache | Container lifetime | First repository | Cleanup |
| --- | --- | ---: | ---: | ---: |
| 00:00 | NFS | 1,679 s | 866.667 s | 518.455 s |
| 01:00 | NFS | 1,566 s | 834.818 s | 415.454 s |
| 02:00 | Local | 304 s | 172.641 s | 13.299 s |
| 03:00 | Local | 267 s | 166.208 s | 13.720 s |

The first local repository recorded 810 cache gets with a 3 ms median and
3,893 ms maximum, and 709 sets with a 4 ms median and 4,672 ms maximum.
Cleanup checked 906 index entries without expiring any; content verification
took 13.200 seconds and retained 882 contents totaling 6,637,354 bytes, with
none removed. Cleanup finished before the successful process exit.

The repeat's first repository recorded 741 cache gets with a 20 ms median
and 5,936 ms maximum, and 507 sets with a 30 ms median and 6,873 ms maximum.
Cleanup checked 906 index entries without expiring any. Verification took
13.628 seconds, retained 878 contents totaling 6,638,955 bytes, and removed
607 totaling 5,214,606 bytes. The shorter cleanup therefore also held when
the populated cache required removal of orphaned contents.

The 02:00 full-run metrics covered 296.465 seconds with 21 samples and no resets:
mean CPU 0.752 cores, throttled periods 4.12%, I/O PSI full 0.116%, and peak
sampled working set 1,645 MiB. Node status snapshots and ten retained condition
samples showed `acer` Ready without memory, disk, or PID pressure. Finalization
contained only one metric sample, so phase CPU/throttling/PSI rates are
unavailable; they must not be reported as zero.

The 03:00 full-run metrics covered 258.898 seconds with 18 samples and no
counter resets: mean CPU 0.819 cores, throttled periods 4.28%, I/O PSI full
0.161%, and peak sampled working set 1,641 MiB. Node snapshots and nine
retained condition samples again showed Ready without pressure. Its short
finalization also contained only one sample, leaving phase rates unavailable.

Storage and node placement changed together, and cache contents and operation
counts differ across runs. This is an operational comparison, not an isolated
NFS benchmark. Both local runs substantially reduced the measured cache
delays and finished with more than 34 minutes of deadline headroom. These
distinct scheduled successes establish the scoped runtime improvement; the
historical mutex holder is still unidentified.

## Diagnostic cleanup

This follow-up removes the four temporary INFO remaps from `config.js` after
the comparison. It changes no image, cache semantics, resource settings,
schedule, deadline, credentials, or full dry-run policy. The config fixture
requires the remap property to be absent; the standalone pinned timing fixture
retains its own remaps for historical reproduction. Raw logs remain restricted.
