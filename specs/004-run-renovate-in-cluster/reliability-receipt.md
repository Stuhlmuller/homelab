# Renovate runtime reliability investigation

Status: local-cache candidate prepared; deployment and acceptance pending.
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

## October 30 instrumented run

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

## Selected candidate and acceptance

Move the complete rebuildable cache to `renovate-cache-local`, a retained
static claim on `acer`, keeping the existing NFS claim declared. This removes
the shared NFS path from the measured backend operations and cleanup without
changing Renovate's file-cache semantics or introducing Redis persistence.
The image, resource limits, schedule, full dry-run mode, 2,400-second deadline,
repository/private caching, and default TTLs remain unchanged. The initializer
changes only mount-root ownership/mode and accepts populated caches.

The 20 GiB local capacity is advisory, with no quota or node failover. It does
not satisfy dedicated capacity or recovery acceptance. Preserve the staged NAS
resources and all migration gates. The runtime evidence supports testing this
storage change, not a claim that NFS alone caused the earlier mutex failures.

Before acceptance, verify both Argo Applications, exact PV/PVC binding, the
initializer/main security contexts, and repeated distinct scheduled Pods
completing all nine repositories and cleanup without errors or mutex markers
within the unchanged deadline. Compare the numeric cache/cleanup timings.
Faster completion and persistent binding do not prove same-key datasource
reuse or normal refresh; those migration acceptance claims remain separate.
Keep raw logs restricted. Remove temporary timing remaps through reviewed
GitOps after the comparison receipt and before enabling writes.
