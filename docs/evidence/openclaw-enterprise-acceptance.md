# OpenClaw Enterprise Acceptance Ledger

Status: **legacy stopped; archive and replacement rollout pending**.
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
| Full platform image catalog and transitive render | [failed mirror `39188058137`](https://github.com/Stuhlmuller/homelab/actions/runs/39188058137); [main `93b641a7`, full retry `39190983355`](https://github.com/Stuhlmuller/homelab/actions/runs/39190983355) | — | Pending. The full retry failed at item 112/214, the pinned LiteLLM database OCI index, with Harbor's `unique_reference` violation. No complete publication or authenticated pull receipt exists. |
| LiteLLM Linux amd64 child publication | [main `0183db1c`, protected mirror run `39210811031`](https://github.com/Stuhlmuller/homelab/actions/runs/39210811031); `ghcr.io/berriai/litellm-database@sha256:2791e3241d7fa59ad942c54c237fb0d53a140b52fad2bd4b40c14a873dbc14a8` | — | Passed exact-current-main guard, source digest check, and complete authenticated Harbor pull. This one-image scope does not pass the full-catalog T004 gate. |
| Legacy off-NAS archive bucket | [main `2841475f`, protected apply `39110519607`](https://github.com/Stuhlmuller/homelab/actions/runs/39110519607) | — | Applied; read-only check confirmed versioning, KMS encryption and public-access block. Archive write/restore pending. |
| Legacy pre-shutdown inventory | [main `d55e2ab8`, run `39127113354`](https://github.com/Stuhlmuller/homelab/actions/runs/39127113354); [main `6de59d7c`, protected recovery `39142331296`](https://github.com/Stuhlmuller/homelab/actions/runs/39142331296) | `e8663e8451f7d76acfdd91904b7a9373a738ef5de44195ac4127ff862389307b` | Passed: the private success marker and both retained baseline copies match this digest; protected publication verified current source identities, one KMS-encrypted S3 version, and a versioned download matching the baseline. Old writers were active at this pre-shutdown gate; the next row records their shutdown. |
| Legacy stopped with zero writers | [main `f818b41b`, reviewed shutdown PR #1350](https://github.com/Stuhlmuller/homelab/pull/1350); Argo `openclaw` synced to that revision at 2026-10-18 16:15:52 UTC | `da89c8f5fde25808175f667767d3a46e06663e58ddb9efd2bfcc55a79ca54d2e` | Passed at 16:17 UTC: Deployment 0 desired/ready, zero gateway Pods, backup CronJob suspended with zero active Jobs, reader Ready on the expected node, and four retained PVC/PV identities verified. Private read-only status receipt retained outside Git. |
| Legacy post-shutdown inventory | [main `e48bcbe7`, run `39157724373`](https://github.com/Stuhlmuller/homelab/actions/runs/39157724373); [verification `39170006465`](https://github.com/Stuhlmuller/homelab/actions/runs/39170006465) | `cd0845fa234c374609e1196f182ac82ed525340bad2b52a21f88fee42b4e1ea4` | Full stopped-source scan, one versioned off-NAS object, matching downloaded bytes and KMS encryption verified. |
| Full independent legacy archive/restore | [earlier attempts `39144330916`](https://github.com/Stuhlmuller/homelab/actions/runs/39144330916), [`39170731077`](https://github.com/Stuhlmuller/homelab/actions/runs/39170731077); [detached attempt `39181763037`](https://github.com/Stuhlmuller/homelab/actions/runs/39181763037); [merged repair #1401](https://github.com/Stuhlmuller/homelab/pull/1401); [main `2f94bec3`, retry `39204434898`](https://github.com/Stuhlmuller/homelab/actions/runs/39204434898); [checksum repair #1416](https://github.com/Stuhlmuller/homelab/pull/1416); [archive launcher `39207560733`](https://github.com/Stuhlmuller/homelab/actions/runs/39207560733) | — | Pending. `39204434898` failed before worker creation because the workflow's pinned helper checksum was stale; #1416 updated that guard. Launcher `39207560733` passed, but its detached worker was OOM-killed during local `verify_bundle` under the reader's 512 MiB limit. No private result or offsite restore receipt exists. Keep the original sources and unpublished partial scratch intact pending a tested streaming-verifier retry. |
| Capacity and isolated canary | Read-only node/top/Talos mount snapshots through 2026-10-19 17:07 UTC | — | Blocked: no isolated canary or admitted local-storage and memory placement. Admission and platform activation remain disabled. |
| Talos node-by-node ladder | Pending | — | Pending |
| Istio minor ladder | Pending | — | Pending |
| Kubernetes 1.35.9 | Pending | — | Pending |
| Firewall canary and node expansion | Pending | — | Pending |
| Envoy/Gateway API private route | Pending | — | Pending |
| PostgreSQL roles/TLS and isolated restore | Pending | — | Pending |
| Enterprise install and hook failure matrix | Pending | — | Pending |
| Inactive agent reconciliation and retry | Pending | — | Pending |
| Model credential and real provider probe | Pending | — | Pending |
| Browser, native origin and network denials | Pending | — | Pending |
| Complete new-state independent restore | Pending | — | Pending |
| 24-hour observation and selective retirement | Pending | — | Pending |

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
restore-only policies exist only in source. The remaining 18 live policies
are generated by Cordium Genesis (3), Octelium Genesis (4), Octelium
Enterprise Genesis (10), and Kiali's OpenAPI generator (1). Their exact
generator outputs and rule intent remain unverified. Nine ingress rules admit
all sources on fixed ports; eight are mesh HBONE TCP/15008, and Kiali's
operator-owned rule covers TCP/20001 and TCP/9090. No source rule is changed
from render equality alone. Owner decisions and real canary enforcement remain
pending, so firewall activation is blocked. Private snapshots and detailed
findings were not committed.
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

Relevant source or policy changes invalidate affected receipts. Keep the
strict broad-egress finding for stock Enterprise public TCP/443 visible during
network acceptance; it is an accepted scoped limitation, not proof of global
destination filtering.
