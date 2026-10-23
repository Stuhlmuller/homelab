# OpenClaw Enterprise Acceptance Ledger

Status: **legacy stopped; archive independently verified; replacement pending**.
Platform prerequisites have only offline source validation. No live upgrade,
firewall enforcement, Envoy route or isolated canary is active; measured nodes
do not admit an isolated canary without evicting unrelated stateful workloads.

This public ledger contains only sanitized source identifiers, immutable
artifact references, private receipt hashes and pass/fail outcomes. Full
inventories, credentials, diagnostics, model prompts and backups stay private.

| Gate | Source or artifact | Private receipt hash | Result |
| --- | --- | --- | --- |
| Pinned stock source | `33bb74590a749f37934da4502fca6035cd234a55` | — | Verified source and paired build |
| Stock controller/runtime publication | [main `3814835f`, run `39103518827`](https://github.com/Stuhlmuller/homelab/actions/runs/39103518827); controller `sha256:8d0d0565bfcc14b070d55434557704480713c97819fe80f490bc046458241164`, runtime `sha256:649351619d6a6697671ceb8bca36c8fd104ff0416e1a652095ce5de6fbf437b6` | — | Signed and fully pulled by protected workflow |
| Full platform image catalog and transitive render | [main `73fbf4c`, full mirror `39906968373`](https://github.com/Stuhlmuller/homelab/actions/runs/39906968373); [earlier `39694217983`](https://github.com/Stuhlmuller/homelab/actions/runs/39694217983) | — | Pending. Run `39906968373` stopped at item 196/214, `quay.io/prometheus/prometheus:v3.11.3-distroless@sha256:cff72a3f49918f41c4b5c8a6174dd8433036bebf7878120da538b3720ba3fa0d`, with public `destination-copy` / `command-failed` on 2026-10-23 11:16 UTC. The earlier run stopped at item 179/214 with `authenticated-pull` / `server-error`. Neither produced a complete authenticated catalog receipt; the new one-image qualification scope cannot pass T004 alone. Any later full receipt must match the reviewed publication bundle. |
| Pinned Prometheus one-image qualification | [main `12bb86c84beffd8a7260049fa46abb3deeefa664`, protected `prometheus` mirror `39949606211`](https://github.com/Stuhlmuller/homelab/actions/runs/39949606211); `quay.io/prometheus/prometheus:v3.11.3-distroless@sha256:cff72a3f49918f41c4b5c8a6174dd8433036bebf7878120da538b3720ba3fa0d` | — | Passed 2026-10-23 12:14 UTC: exact-current-main guard, matching digests and complete authenticated Harbor pull. This fixed one-image scope does not pass full-catalog T004. |
| LiteLLM Linux amd64 child publication | [main `0183db1c`, protected mirror run `39210811031`](https://github.com/Stuhlmuller/homelab/actions/runs/39210811031); `ghcr.io/berriai/litellm-database@sha256:2791e3241d7fa59ad942c54c237fb0d53a140b52fad2bd4b40c14a873dbc14a8` | — | Passed exact-current-main guard, source digest check, and complete authenticated Harbor pull. This one-image scope does not pass the full-catalog T004 gate. |
| Legacy off-NAS archive bucket | [main `2841475f`, protected apply `39110519607`](https://github.com/Stuhlmuller/homelab/actions/runs/39110519607) | — | Applied; read-only check confirmed versioning, KMS encryption and public-access block. Publication and separate verification restored the versioned off-NAS objects. |
| Legacy pre-shutdown inventory | [main `d55e2ab8`, run `39127113354`](https://github.com/Stuhlmuller/homelab/actions/runs/39127113354); [main `6de59d7c`, protected recovery `39142331296`](https://github.com/Stuhlmuller/homelab/actions/runs/39142331296) | `e8663e8451f7d76acfdd91904b7a9373a738ef5de44195ac4127ff862389307b` | Passed: the private success marker and both retained baseline copies match this digest; protected publication verified current source identities, one KMS-encrypted S3 version, and a versioned download matching the baseline. Old writers were active at this pre-shutdown gate; the next row records their shutdown. |
| Legacy stopped with zero writers | [main `f818b41b`, reviewed shutdown PR #1350](https://github.com/Stuhlmuller/homelab/pull/1350); Argo `openclaw` synced to that revision at 2026-10-18 16:15:52 UTC | `da89c8f5fde25808175f667767d3a46e06663e58ddb9efd2bfcc55a79ca54d2e` | Passed at 16:17 UTC: Deployment 0 desired/ready, zero gateway Pods, backup CronJob suspended with zero active Jobs, reader Ready on the expected node, and four retained PVC/PV identities verified. Private read-only status receipt retained outside Git. |
| Legacy post-shutdown inventory | [main `e48bcbe7`, run `39157724373`](https://github.com/Stuhlmuller/homelab/actions/runs/39157724373); [verification `39170006465`](https://github.com/Stuhlmuller/homelab/actions/runs/39170006465) | `cd0845fa234c374609e1196f182ac82ed525340bad2b52a21f88fee42b4e1ea4` | Full stopped-source scan, one versioned off-NAS object, matching downloaded bytes and KMS encryption verified. |
| Full independent legacy archive/restore | [source archive `39366476872`](https://github.com/Stuhlmuller/homelab/actions/runs/39366476872); [publication `9f64b56a15c8a1c1b81606e0fa751157b09f47fb/39501240221`](https://github.com/Stuhlmuller/homelab/actions/runs/39501240221); [separate verification on `90d3d413`, run `39910018168`](https://github.com/Stuhlmuller/homelab/actions/runs/39910018168) | — | Passed T013. Protected publication uploaded the versioned archive and receipt, restored both objects and wrote a private final receipt. The separate protected `verify` run succeeded on 2026-10-23 09:52 UTC after retrieving the exact published versions and independently restoring the full local/NAS trees, both SQLite databases, NAS workspace/configuration, and historical backup directories. Local source and partial attempts remain retained. |
| Legacy compatible recovery rehearsal | [read-only image and mount review on `90f7338`, 2026-10-20](https://github.com/Stuhlmuller/homelab/commit/90f733820e1c51b3b5a17c0743e606e6439a3d4c); [first protected `prepare-restore` run `39942297939`](https://github.com/Stuhlmuller/homelab/actions/runs/39942297939); [retry `39951803625`](https://github.com/Stuhlmuller/homelab/actions/runs/39951803625); [ranged-transfer retry `39966041305`](https://github.com/Stuhlmuller/homelab/actions/runs/39966041305) | — | Pending. The first run failed in broad `verification` with an incomplete archive; the second failed in fixed `verification-archive-download` at 2026-10-23 13:04 UTC. The bounded-range retry failed in the same fixed phase at 16:10 UTC, leaving no promoted archive or receipt in run-private scratch. None reached the private restore worker, completed marker or accepted recovery copy. The cause remains unclassified between versioned source-range fetch and reader transfer/write; the next protected retry has fixed public subphases for each failure boundary. Six external `/app` symlinks resolve to five nonempty directories in the pinned image baseline, but the former gateway's writable overlay may have changed them and has not been compared with retained evidence. Three dangling external targets also remain unclassified. The offsite archive passed independent verification; writable local/NAS recovery copies, enforced offline network boundary, and isolated old-image boot remain pending. Original claims remain retained and mounted read-only by the reader. |
| Capacity and isolated canary | [earlier read-only checks, PR #1539](https://github.com/Stuhlmuller/homelab/pull/1539); 2026-10-23 08:18 UTC recheck below | — | Blocked. Acer is 503 MiB short of database plus gateway, and the initial 4 GiB API/worker/database/Envoy/gateway planning reservation would be about 2,295 MiB short if co-located there; both exclude transient margin. Every Zima worker has less than 10 GiB filesystem free for one required claim. No isolated tainted canary or admitted Enterprise placement. T022, T027 and T035 remain pending. |
| Talos node-by-node ladder | Pending | — | Pending |
| Istio minor ladder | Pending | — | Pending |
| Kubernetes 1.35.9 | Pending | — | Pending |
| Firewall canary and node expansion | Pending | — | Pending |
| Envoy/Gateway API private route | Pending | — | Pending |
| PostgreSQL roles/TLS and isolated restore | Pending | — | Pending |
| Private browser access source | [access PR #1420](https://github.com/Stuhlmuller/homelab/pull/1420), `bd5bd437`; [installation PR #1424](https://github.com/Stuhlmuller/homelab/pull/1424), `e24dc89` | — | Source validated: authenticated Octelium console and post-auth redirect, opaque native-host private route and DNS/certificate from #1420; cookie and trusted-proxy declarations from #1424. Live URL cutover and browser/TLS/WebSocket acceptance remain pending. |
| Protected Enterprise operations stages | [workflow](../../.github/workflows/openclaw-enterprise-operations.yml), [stage guard](../../scripts/ci/openclaw-enterprise-stage.sh), [journal dispatcher](../../scripts/ci/openclaw-enterprise-journal-operator.py) | — | Source-only. Fixed dispatch is guarded and serialized; full-sync blocks on the unselected installation phase. Reconcile, stop and verification have a source-bound in-cluster Job with a retained journal PVC, but its disabled declaration lacks verified placement, PV/image identities and bootstrap credential. Binding needs an owner-controlled private key; restore and acceptance remain blocked. T041/T043 and live outcomes remain pending. |
| Enterprise install and hook failure matrix | Pending | — | Pending |
| Inactive agent reconciliation and retry | Pending | — | Pending |
| Model credential and real provider probe | Pending | — | Pending |
| Browser, native origin and network denials | Pending | — | Pending |
| Complete new-state independent restore | Pending | — | Pending |
| 24-hour observation and selective retirement | Pending | — | Pending |
| T059 source documentation and OpenWiki refresh | [merged PR #1560](https://github.com/Stuhlmuller/homelab/pull/1560), main `0e223d6`; protected static, lint, image-policy, network-policy and release-dry-run checks passed | — | Passed for source documentation only: five named runbooks updated and affected OpenWiki pages refreshed by the native update path. Capacity, credentials, policy enforcement, platform upgrades and Enterprise live acceptance remain pending. |

Earlier publication attempts failed during source reads or after upload; none
produced a final offsite receipt. The [detached source archive `39366476872`](https://github.com/Stuhlmuller/homelab/actions/runs/39366476872)
used the stopped [baseline `39157724373`](https://github.com/Stuhlmuller/homelab/actions/runs/39157724373).
[Protected `publish-archive` run `39501240221`](https://github.com/Stuhlmuller/homelab/actions/runs/39501240221)
used that source archive reference and completed at 2026-10-21 02:58 UTC. At
its reviewed source SHA, success follows a versioned off-NAS upload, receipt
upload, restore of both objects, archive verification and private final receipt
write. The later [`39700564687`](https://github.com/Stuhlmuller/homelab/actions/runs/39700564687)
and [`39908653791`](https://github.com/Stuhlmuller/homelab/actions/runs/39908653791)
retries mistakenly passed the publication run as an archive-worker reference.
The former failed in the old broad `baseline` phase; the latter failed
specifically at `publication-archive-result` before upload. Neither invalidates
the successful publication. Separate [verify run `39910018168`](https://github.com/Stuhlmuller/homelab/actions/runs/39910018168)
succeeded against the exact publication reference
`9f64b56a15c8a1c1b81606e0fa751157b09f47fb/39501240221`. Its protected
stage rechecked stopped writers, fetched the versioned final receipt and its
specified archive/receipt objects, and ran the multi-root restore verifier.
The verifier binds both SQLite databases and full local/NAS content, including
required NAS workspace, configuration, backup and checkpoint directories.
The independent T013 receipt is the public run reference above; private
receipt contents and version IDs remain outside Git.
T038 originally assigned `private-access.yaml` to the Enterprise foundation.
[PR #1420](https://github.com/Stuhlmuller/homelab/pull/1420) moved the
fixed Services to the Octelium catalog and the opaque Agent-host route,
DNS and TLS to Traefik. The checked task and plan use those source owners.

Post-shutdown worker observations: `zimaboard-0` has 96% CPU and 99% memory
requested; `zimaboard-2` has 92% memory requested. `zimaboard-1` has 32% CPU
and 39% memory requested, but 75% actual memory in use and hosts Argo, database,
access, and other unrelated Pods without the proposed canary taint toleration.
Tainting it would prevent those Pods from rescheduling after a restart. These
snapshots do not establish peak headroom, local storage allocation, or T022
admission. Authenticated Talos disk inspection was unavailable from that
checkout's empty `.talos/talosconfig`; the later authenticated inspection is
recorded below.

Do not infer a passed gate from a manifest, green Pod, local fixture or an
empty receipt cell. Record the exact current-main SHA, workflow run and
receipt digest beside each result after the corresponding protected stage.
Read-only pre-shutdown sizing on 2026-10-18 found 21,799,200 KiB in the NAS
claim and about 381 MiB in the local runtime; the NAS reported 853 GiB free.
The archive needs a separate NAS-backed scratch claim and a verified off-NAS
copy. Recheck source size, free space, placement and restore headroom immediately
before shutdown; these observations do not pass the capacity or recovery gate.
The [read-only policy baseline](openclaw-enterprise-policy-review.json) was
refreshed at 2026-10-19 02:30 UTC: 66 live policies and 209 active Pods. The
inventory flags 196 unisolated Pods, 178 Pods requiring separate review,
21 unreviewed egress policies, and 18 strict wildcard-egress findings.
The three new Mastodon policies are included. All 51 repository Kustomizations
rendered 50 distinct policies; 48 live policies matched their complete source
specs after normalizing only Kubernetes' absent-versus-empty rule lists. Two
restore-only policies exist only in source. At that checkpoint, the remaining
18 live policies were generated by Cordium Genesis (3), Octelium Genesis (4),
Octelium Enterprise Genesis (10), and Kiali's OpenAPI generator (1). The later
source-bound fixtures cover all 17 Genesis policies; their traffic and
broad-rule intent remain unqualified. Nine ingress rules admit
all sources on fixed ports; eight are mesh HBONE TCP/15008, and Kiali's
operator-owned rule covers TCP/20001 and TCP/9090. No source rule is changed
from render equality alone. Nine repository-owned DNS egress rules select
only CoreDNS Pods on TCP/UDP 53, matching the live `kube-dns` Service selector;
six were narrowed in this review, while three already had that selector.
the policy review records their new source and render hashes separately from
the earlier live baseline. Their live reconciliation and enforced DNS traffic,
generated-owner decisions, and real canary enforcement remain pending, so
firewall activation is blocked. Private snapshots and detailed findings were
not committed.
At 2026-10-20 00:38 UTC, a read-only recheck of the three Cordium Genesis
policies matched their saved complete-spec hashes and the reviewed v0.12.7
constructors. Their [expected-spec fixture](../../clusters/homelab/apps/cordium-bootstrap/generated-networkpolicies.json)
is an additional inventory render input, not a live policy owner. Kiali's
operator policy was separately replaced by source-owned equivalent policy;
at that checkpoint 14 Cordium/Octelium-generated policies lacked bound render
fixtures.
`cordium/ws-main` public all-port egress, actual traffic, and the tainted
canary remain unqualified; this does not pass T018 or T027.
On October 20, the four Octelium Genesis policies also matched a read-only
live complete-spec recheck and the reviewed v0.35.0 constructors. Their
[expected-spec fixture](../../clusters/homelab/apps/octelium/generated-networkpolicies.json)
is another inventory render input, not a live owner. At that checkpoint, ten
Octelium Enterprise Genesis policies lacked source-bound fixtures. `octelium/svc-upstream`
public all-port egress, actual traffic, and the tainted canary remain
unqualified; T018 and T027 remain open.
On October 20, the ten Octelium Enterprise Genesis policies also matched a
read-only complete-spec check against the reviewed v0.22.0 constructors. Their
[expected-spec fixture](../../clusters/homelab/apps/octelium-enterprise/generated-networkpolicies.json)
is an additional inventory input, not a deployed policy. All 17 generated
Cordium, Octelium, and Octelium Enterprise policies now have source-bound
fixtures. Their traffic, broad `ws-main` and `svc-upstream` egress, and the
isolated canary remain unqualified; T018 and T027 remain open.

At 2026-10-20 17:59 UTC, a fresh read-only inventory found the same 209 active
Pods and 66 live policies. All 49 live source-owned policies match current
Kustomize renders after only absent-versus-empty rule-list normalization; the
17 Genesis-owned policies match their pinned complete-spec fixtures and live
managedFields owners. Six rendered policies are absent from live state: two
restore overlays and four dormant Enterprise policies. There is no observed
policy drift. The current inventory still reports 196 Pods without egress
isolation, 21 unreviewed egress policies, ten strict wildcard-egress rules
across nine policies, and nine all-source ingress rules. The earlier 18-rule
wildcard count remains a historical snapshot, not a current finding count.
The six corrected DNS policies now match live specs, but DNS traffic, generated
all-port public egress, ingress clients and lifecycle behavior still need
isolated-canary proof. T018 and T027 remain open; firewall enforcement remains
disabled. See the dated owner and render-hash audit in the policy review.
Read-only `kubectl top nodes` at 2026-10-18 11:57 UTC showed memory use of
69% on `acer`, 82% on `zimaboard-0`, 85% on `zimaboard-1` and 81% on
`zimaboard-2`; all four nodes were Ready and none had a dedicated canary
taint. These are point-in-time observations before legacy shutdown, not
placement admission. Recheck requests, peaks, daemonset overhead and storage
after US2; do not select or taint a canary from this snapshot.
At 2026-10-18 12:47 UTC, read-only node allocation showed memory requests
of 88% (`acer`), 99% (`zimaboard-0`), 68% (`zimaboard-1`) and 92%
(`zimaboard-2`). The legacy gateway and retirement reader both occupy
`zimaboard-1`; neither this request snapshot nor their eventual removal
proves safe canary capacity.

At 2026-10-19 02:16 UTC, after the legacy gateway shutdown, read-only
`kubectl top nodes` showed memory use of 71% (`acer`), 83%
(`zimaboard-0`), 72% (`zimaboard-1`) and 74% (`zimaboard-2`). Active
Pod memory requests were 88%, 98%, 40% and 92% of allocatable memory,
respectively. `zimaboard-1` still hosted 40 active Pods and seven
hostPath PVs declaring 43.3 GiB, including the three retained OpenClaw
local PVs declaring 10 GiB. No node had a canary taint. These are
point-in-time requests and usage, not measured peaks or physical local-disk
free space. A dedicated isolated canary is still unavailable; placement
and T022 remain pending.

At 2026-10-19 03:37 UTC, a fresh read-only check found memory use of
70% (`acer`), 85% (`zimaboard-0`), 74% (`zimaboard-1`) and 70%
(`zimaboard-2`); memory requests were 88%, 99%, 44% and 92% of
allocatable RAM, respectively. All nodes were Ready and untainted.
`zimaboard-1` had 42 active Pods, including 36 non-DaemonSet Pods,
and seven node-affine local PVs: three retained OpenClaw volumes, two
Cordium workspaces, and Mastodon's PostgreSQL and Redis volumes.
Its 7,282 MiB allocatable RAM minus 5,441 MiB reported use leaves
about 1,841 MiB observed margin, below the proposed roughly 4 GiB
Enterprise steady reservation before transient jobs and system headroom.
A `NoSchedule` canary taint would leave those unrelated Pods exposed to
firewall qualification and could strand their replacements after reboot;
vacating the node would evict unrelated stateful apps. The other workers
are 99% and 92% reserved; `acer` is the sole control plane and 88%
reserved. No existing node qualifies as an isolated canary under T022's
no-unrelated-eviction and no-new-hardware constraint. These are
point-in-time observations, not measured peaks; T022 remains blocked.

At 2026-10-19 17:07 UTC, read-only `kubectl top nodes`, node allocation and
authenticated Talos `/var` mounts showed:

| Node | Memory requested / allocatable | Actual memory used | `/var` free |
| --- | ---: | ---: | ---: |
| `acer` | 13,459 / 15,261 MiB (88%) | 10,978 MiB (71%) | 411.67 GB |
| `zimaboard-0` | 7,276 / 7,282 MiB (99%) | 6,270 MiB (86%) | 5.39 GB |
| `zimaboard-1` | 3,756 / 7,282 MiB (51%) | 6,253 MiB (85%) | 10.01 GB |
| `zimaboard-2` | 1,206 / 1,308 MiB (92%) | 991 MiB (75%) | 9.29 GB |

Each worker has only one writable 31 GB eMMC disk and no separate local data
volume. Each has less than the 10 GiB (10.74 GB) free required for even one
full new PostgreSQL or agent allocation; the three distinct planned volumes
total 21 GiB. Only `acer` has measured disk space for them, but its 1,802 MiB
unreserved memory is about 503 MiB below the plan's initial 512 MiB database
plus 1,792 MiB gateway reservation, before API, worker, Envoy, enforcement,
transient jobs or headroom. Retained old local volumes are not reclaimable.
The five non-infrastructure Pods on `zimaboard-2` include single-replica
Langfuse PostgreSQL with `Recreate` rollout; tainting that node would expose
them to canary enforcement or strand their replacements, while relocating the
database would interrupt it. These snapshots are not peak measurements and do
not admit T022, T035, an isolated canary, or Enterprise activation.

At 2026-10-19 19:50 UTC, read-only node allocation, `kubectl top`, kubelet
filesystem statistics and authenticated Talos disk inventory still found
`acer` 13,459 / 15,261 MiB requested / allocatable, with 411.89 GB free on
its 500 GB disk. Its 1,802 MiB unreserved RAM is over 502 MiB short of the
2,304 MiB PostgreSQL-plus-gateway minimum. The three workers still have only
one writable 31 GB eMMC each, with 5.39, 10.01 and 9.29 GB filesystem free;
none can hold one new 10 GiB claim. Adding at least 503 MiB usable RAM to
`acer` would address only that request deficit, not transient headroom or the
separate isolated-canary requirement; hardware expansion feasibility is
unverified.

`zimaboard-2` still has only 102 MiB unreserved. Its five ordinary Pods
request 672 MiB and 410m CPU in total. Removing them through reviewed source
changes would leave about 774 MiB and 1,450m for the policy enforcer and
qualification Pods. `zimaboard-1` has 4,038 MiB unreserved, enough by request
arithmetic for those Pods and a 768 MiB Grafana relocation from `acer`.
That would leave only about 266 MiB above Enterprise's minimum on `acer` and,
at current observed use, about 800 MiB on `zimaboard-1` before peaks and
rolling overlap. Grafana and Langfuse PostgreSQL are single-replica
`Recreate` workloads; moving them would interrupt unrelated services. No
peak or transient fit is proven, and a taint alone would not remove
already-running Pods. This candidate does not admit T022.

At 2026-10-20 01:47 UTC, after the legacy shutdown, all four nodes were Ready,
reported no memory, disk or PID pressure, and had no canary taint. Read-only
`kubectl describe node` and `kubectl top nodes` showed:

| Node | Unreserved memory | Current node memory use | 24-hour Pod working-set peak |
| --- | ---: | ---: | ---: |
| `acer` | 1,801.7 MiB | 11,259 MiB | 10,897 MiB |
| `zimaboard-0` | 5.5 MiB | 6,167 MiB | 4,697 MiB |
| `zimaboard-1` | 3,909.5 MiB | 5,647 MiB | 5,997 MiB |
| `zimaboard-2` | 230.1 MiB | 924 MiB | 521 MiB |

The peak is Prometheus `max_over_time` of the per-node sum of non-sandbox
container working sets over 24 hours at five-minute resolution (288 samples
per node). It excludes host processes, so it is not free-memory proof.
`zimaboard-1` is the best worker by requests, yet its 3,909.5 MiB margin is
186.5 MiB below the initial 4,096 MiB Enterprise steady reservation before
startup, backup, enforcement and system headroom. Its 5,997 MiB Pod peak leaves
at most about 1,284 MiB of allocatable RAM before host overhead. It already
hosts 43 running Pods, including infrastructure DaemonSets and the retained
legacy reader; a `NoSchedule` taint would not isolate them. No existing worker
qualifies as the dedicated canary without moving unrelated workloads. The
independent legacy archive/restore passed; measured storage/transient placement
remains pending, so T022 stays unchecked.

At 2026-10-20 07:22 UTC on `main` `cefa1440`, another read-only
`kubectl describe node`, `kubectl top nodes`, running-Pod inventory and kubelet
`/stats/summary` recheck found all four nodes untainted:

| Node | Memory requested / allocatable | Actual memory used | Running Pods | Root filesystem free |
| --- | ---: | ---: | ---: | ---: |
| `acer` | 13,459 / 15,261 MiB | 10,866 MiB | 76 | 411.61 GB |
| `zimaboard-0` | 7,276 / 7,282 MiB | 6,046 MiB | 81 | 5.41 GB |
| `zimaboard-1` | 3,884 / 7,282 MiB | 6,447 MiB | 45 | 9.71 GB |
| `zimaboard-2` | 1,078 / 1,308 MiB | 922 MiB | 9 | 9.29 GB |

The best worker, `zimaboard-1`, now has about 3,398 MiB unreserved by request,
698 MiB below the initial 4,096 MiB Enterprise reservation. Its point-in-time
usage leaves only about 835 MiB of allocatable RAM before host overhead, so no
peak or rolling-overlap margin is established. Every worker also has less than
10.74 GB free for one new 10 GiB local claim. Existing Pods remain on each
worker; a `NoSchedule` taint cannot isolate them. The previously considered
Grafana/Langfuse relocations still interrupt single-replica services and have
no proven transient fit. This recheck does not admit storage, a canary or T022.

At 2026-10-20 13:07–13:15 UTC on `main` `4c4b308d`, a read-only
`kubectl describe nodes`, `kubectl top nodes`, node/Pod/PV/DaemonSet inventory,
and kubelet `/stats/summary` recheck found the old gateway at 0/0 replicas,
all four nodes Ready with no pressure or taints, and no policy-enforcer
DaemonSet. Authenticated Talos mounts confirmed each worker's `/var` is on
`/dev/mmcblk0p4`, with no separate local-data mount under `/var/lib` outside
kubelet-managed volumes:

| Node | CPU requested / allocatable | CPU used | Memory requested / allocatable | Memory used | Root filesystem free |
| --- | ---: | ---: | ---: | ---: | ---: |
| `acer` | 5,036 / 7,950m | 1,032m | 13,459 / 15,261 MiB | 10,867 MiB | 411.59 GB |
| `zimaboard-0` | 3,851 / 3,950m | 2,417m | 7,276 / 7,282 MiB | 6,160 MiB | 5.39 GB |
| `zimaboard-1` | 1,758 / 3,950m | 1,205m | 3,884 / 7,282 MiB | 6,308 MiB | 9.74 GB |
| `zimaboard-2` | 885 / 1,950m | 224m | 1,078 / 1,308 MiB | 917 MiB | 9.29 GB |

The best worker still has only about 3,398 MiB unreserved, 698 MiB short of
the initial 4,096 MiB Enterprise steady reservation before jobs, enforcement
and headroom. If T035 uses the existing `/var/lib` local-PV pattern, every
worker has less than the 10.74 GB needed for one new 10 GiB claim;
`zimaboard-1` retains three old OpenClaw local PVs declaring 10 GiB total.
The new paths are uncommitted and must be checked at T035. PV capacities are
not filesystem quotas. `acer` has disk space, but only about 1,802 MiB
unreserved RAM, below
the 2,304 MiB database-plus-gateway minimum. Every worker still runs unrelated
non-DaemonSet Pods, so a `NoSchedule` taint would not isolate a canary.
These point-in-time readings do not prove peak or rolling-update fit. T022,
storage placement and canary admission remain blocked.

At about 2026-10-20 21:00 UTC, a fresh read-only node, Pod and kubelet
filesystem check still found all four nodes Ready and untainted. Unreserved
memory by request was about 1,801 MiB on `acer`, 5 MiB on `zimaboard-0`,
3,397 MiB on `zimaboard-1`, and 230 MiB on `zimaboard-2`. Kubelet root
filesystem free space was 382.7, 5.03, 9.08 and 8.65 GiB, respectively.
No worker has the free space for one new 10 GiB local claim, let alone the
distinct 10 GiB database, 10 GiB agent and 1 GiB bootstrap claims in T035.
`acer` has disk space but remains below the 2,304 MiB database-plus-gateway
request before API, worker or headroom. `zimaboard-1` still runs 44 Pods,
including the retained reader and unrelated stateful workloads;
`zimaboard-2` runs unrelated apps and system Pods. No custom canary taint
tolerations are declared. A `NoSchedule` taint would not isolate already
running Pods and could strand replacements after restart. T022, T027 and
T035 remain blocked; no node was tainted or workload relocated.

At 2026-10-23 05:12 UTC on `main` `d75110b`, read-only node allocation,
running-Pod requests, `kubectl top nodes`, and kubelet `/stats/summary` still
found no taints or safe existing-node placement:

| Node | Memory requested / allocatable | Actual memory used | Running Pods | Node filesystem free |
| --- | ---: | ---: | ---: | ---: |
| `acer` | 13,459 / 15,261 MiB | 10,675 MiB | 76 | 383.20 GiB |
| `zimaboard-0` | 7,276 / 7,282 MiB | 6,201 MiB | 81 | 5.02 GiB |
| `zimaboard-1` | 3,884 / 7,282 MiB | 6,053 MiB | 44 | 9.00 GiB |
| `zimaboard-2` | 1,078 / 1,308 MiB | 939 MiB | 9 | 8.65 GiB |

Only `acer` has filesystem space for even one of T035's 10 GiB local claims;
its roughly 1,801 MiB unreserved memory is 503 MiB below the 2,304 MiB
database-plus-gateway request before transient or system margin. `zimaboard-1`
has 3,397 MiB free by requests but less than 10 GiB disk free. Clearing it
for an isolated canary would need to relocate 38 non-DaemonSet Pods requesting
about 3,342 MiB; the other three nodes together have only about 2,036 MiB
unreserved, before node-bound claims and rollout overlap. `zimaboard-2` has
only 1,308 MiB allocatable total. Rebalancing the declared running workloads
cannot establish both storage and an isolated tainted canary.

At 2026-10-23 08:18 UTC on `main` `bcc08cb`, a read-only request, kubelet
filesystem and Pod check found `acer` still had about 1,802 MiB unreserved by
request and 383.07 GiB filesystem free. The 503 MiB deficit above is only the
2,304 MiB database-plus-gateway floor. The [initial planning budget](../../specs/003-replace-openclaw-enterprise/research.md)
for API, worker, database, Envoy and gateway is 4,096 MiB; co-locating that
planning budget on `acer` exceeds its current unreserved requests by about
2,294 MiB of *allocatable* RAM before startup, backup, enforcement and peak
margins. This co-location is a planning scenario, not a selected placement.
The [placement inputs](../../clusters/homelab/apps/openclaw-enterprise/profile-input.json)
pin API/worker to `oce-role: control`, and the Envoy proxy shares that
[control placement](../../clusters/homelab/apps/openclaw-enterprise/envoyproxy.yaml).
The [pinned upstream driver](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/apps/controller/src/drivers/compute/kubernetes/index.ts)
uses `runtime.nodeSelector` (`oce-role: agents`) for this Embedded Gateway;
`gatewayNodeSelector` applies only to Dedicated Gateways. Its single Gateway
Pod requests 1,792 MiB and mounts a distinct 10 GiB state claim. The 768 MiB
`resources.agent` setting is for a separate Dedicated Harness, per the
[pinned profile guide](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/guides/deploy/installation-profiles.md), and does not
add an Embedded Pod. `zimaboard-1` had a 6,430 MiB node working set against
7,282 MiB allocatable and retains seven node-affine local PVs; it cannot host
a new 10 GiB local Gateway claim. `zimaboard-2` has no local PV, but its four
unrelated Pods request 544 MiB, including single-replica `Recreate` Langfuse
PostgreSQL.
Moving all four elsewhere would leave only 428 MiB by requests after existing
DaemonSets, the proposed 250 MiB enforcer and three 32 MiB fixtures; peak and
service-continuity admission remain unproven. No existing node qualifies under
T022's no-unrelated-eviction rule; no node was relabeled, tainted or moved.

The [Crossplane source](../../IaC/platform-crossplane/stack.hcl) declares
both controller replicas at zero, but the live Argo Application lacks those
Helm parameters and two live Pods on `acer` still request 256 MiB each.
Reconciliation through the protected declared path might reclaim 512 MiB,
leaving only about 9 MiB after the 2,304 MiB minimum. This separate drift
follow-up would not isolate a canary or prove transient fit; no workload was
moved or scaled.

At 2026-10-23 09:32 UTC on `main` `111b58f`, a fresh read-only check found
`acer` at 13,459 / 15,261 MiB requested with 383.01 GiB node filesystem free.
Every worker remained below 10 GiB free. The Embedded Gateway's local 10 GiB
claim and PostgreSQL's local 10 GiB claim therefore both require `acer` under
the proposed storage pattern; their 2,304 MiB combined request exceeds its
1,802 MiB unreserved capacity by 502 MiB before peak or startup margin.
If API, worker and the full 768 MiB Envoy planning allowance instead occupy
`zimaboard-1`, their 1,792 MiB budget leaves only 122 MiB against that node's
observed 1,914 MiB memory margin before peaks; `zimaboard-1` also has only
8.98 GiB filesystem free. This hypothetical split is not an admitted
placement. The earlier separate-768-MiB-Agent arithmetic was incorrect for
Embedded mode and must not be used for capacity admission. `zimaboard-2` still
hosts four unrelated Pods, including single-replica `Recreate` Langfuse
PostgreSQL; no worker satisfies the zero-foreign-Pod canary gate.

Relevant source or policy changes invalidate affected receipts. Keep the
strict broad-egress finding for stock Enterprise public TCP/443 visible during
network acceptance; it is an accepted scoped limitation, not proof of global
destination filtering.
