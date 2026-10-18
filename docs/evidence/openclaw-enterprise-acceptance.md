# OpenClaw Enterprise Acceptance Ledger

Status: **legacy stopped; archive and replacement rollout pending**.
This public ledger contains only sanitized source identifiers, immutable
artifact references, private receipt hashes and pass/fail outcomes. Full
inventories, credentials, diagnostics, model prompts and backups stay private.

| Gate | Source or artifact | Private receipt hash | Result |
| --- | --- | --- | --- |
| Pinned stock source | `33bb74590a749f37934da4502fca6035cd234a55` | — | Verified source and paired build |
| Stock controller/runtime publication | [main `3814835f`, run `39103518827`](https://github.com/Stuhlmuller/homelab/actions/runs/39103518827); controller `sha256:8d0d0565bfcc14b070d55434557704480713c97819fe80f490bc046458241164`, runtime `sha256:649351619d6a6697671ceb8bca36c8fd104ff0416e1a652095ce5de6fbf437b6` | — | Signed and fully pulled by protected workflow |
| Full platform image catalog and transitive render | [main `d7c81d87`, mirror run `39105390894`](https://github.com/Stuhlmuller/homelab/actions/runs/39105390894) | — | Pending |
| Legacy off-NAS archive bucket | [main `2841475f`, protected apply `39110519607`](https://github.com/Stuhlmuller/homelab/actions/runs/39110519607) | — | Applied; read-only check confirmed versioning, KMS encryption and public-access block. Archive write/restore pending. |
| Legacy pre-shutdown inventory | [main `d55e2ab8`, run `39127113354`](https://github.com/Stuhlmuller/homelab/actions/runs/39127113354); [main `6de59d7c`, protected recovery `39142331296`](https://github.com/Stuhlmuller/homelab/actions/runs/39142331296) | `e8663e8451f7d76acfdd91904b7a9373a738ef5de44195ac4127ff862389307b` | Passed: the private success marker and both retained baseline copies match this digest; protected publication verified current source identities, one KMS-encrypted S3 version, and a versioned download matching the baseline. Old writers were active at this pre-shutdown gate; the next row records their shutdown. |
| Legacy stopped with zero writers | [main `f818b41b`, reviewed shutdown PR #1350](https://github.com/Stuhlmuller/homelab/pull/1350); Argo `openclaw` synced to that revision at 2026-10-18 16:15:52 UTC | `da89c8f5fde25808175f667767d3a46e06663e58ddb9efd2bfcc55a79ca54d2e` | Passed at 16:17 UTC: Deployment 0 desired/ready, zero gateway Pods, backup CronJob suspended with zero active Jobs, reader Ready on the expected node, and four retained PVC/PV identities verified. Private read-only status receipt retained outside Git. |
| Legacy post-shutdown inventory | [main `e48bcbe7`, run `39157724373`](https://github.com/Stuhlmuller/homelab/actions/runs/39157724373); [verification `39170006465`](https://github.com/Stuhlmuller/homelab/actions/runs/39170006465) | `cd0845fa234c374609e1196f182ac82ed525340bad2b52a21f88fee42b4e1ea4` | Full stopped-source scan, one versioned off-NAS object, matching downloaded bytes and KMS encryption verified. |
| Full independent legacy archive/restore | [failed archive `39144330916`](https://github.com/Stuhlmuller/homelab/actions/runs/39144330916); [failed archive `39170731077`](https://github.com/Stuhlmuller/homelab/actions/runs/39170731077) | — | Pending. The first run could not verify a SQLite database with WAL directly on the read-only mount; a private writable snapshot fixed that check. The latter completed its stopped-source rescan, but the long archive exec disconnected before any result or off-NAS receipt. The orphan process stopped and left only an unpublished private partial bundle. Do not count either run as a backup. |
| Capacity and isolated canary | Read-only post-shutdown `kubectl describe node`, `kubectl top node` at 2026-10-18 16:18 UTC | — | Blocked: no dedicated node; no existing worker qualifies as a safe tainted canary. Admission and platform activation remain disabled. |
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
admission. Authenticated Talos disk inspection was unavailable because this
checkout's `.talos/talosconfig` is empty.

Do not infer a passed gate from a manifest, green Pod, local fixture or an
empty receipt cell. Record the exact current-main SHA, workflow run and
receipt digest beside each result after the corresponding protected stage.
Read-only pre-shutdown sizing on 2026-10-18 found 21,799,200 KiB in the NAS
claim and about 381 MiB in the local runtime; the NAS reported 853 GiB free.
The archive needs a separate NAS-backed scratch claim and a verified off-NAS
copy. Recheck source size, free space, placement and restore headroom immediately
before shutdown; these observations do not pass the capacity or recovery gate.
The [read-only policy baseline](openclaw-enterprise-policy-review.json) found
61 live policies across 204 Pods; 194 Pods had no selected egress policy.
Source-render and ingress review, owner corrections, and real canary enforcement
remain pending, so firewall activation is blocked.
Relevant source or policy changes invalidate affected receipts. Keep the
strict broad-egress finding for stock Enterprise public TCP/443 visible during
network acceptance; it is an accepted scoped limitation, not proof of global
destination filtering.
