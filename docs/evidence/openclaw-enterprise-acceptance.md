# OpenClaw Enterprise Acceptance Ledger

Status: **pending; no replacement rollout or shutdown has been executed**.
This public ledger contains only sanitized source identifiers, immutable
artifact references, private receipt hashes and pass/fail outcomes. Full
inventories, credentials, diagnostics, model prompts and backups stay private.

| Gate | Source or artifact | Private receipt hash | Result |
| --- | --- | --- | --- |
| Pinned stock source | `33bb74590a749f37934da4502fca6035cd234a55` | — | Verified source and paired build |
| Stock controller/runtime publication | [main `3814835f`, run `39103518827`](https://github.com/Stuhlmuller/homelab/actions/runs/39103518827); controller `sha256:8d0d0565bfcc14b070d55434557704480713c97819fe80f490bc046458241164`, runtime `sha256:649351619d6a6697671ceb8bca36c8fd104ff0416e1a652095ce5de6fbf437b6` | — | Signed and fully pulled by protected workflow |
| Full platform image catalog and transitive render | [main `d7c81d87`, mirror run `39105390894`](https://github.com/Stuhlmuller/homelab/actions/runs/39105390894) | — | Pending |
| Legacy off-NAS archive bucket | [main `2841475f`, protected apply `39110519607`](https://github.com/Stuhlmuller/homelab/actions/runs/39110519607) | — | Applied; read-only check confirmed versioning, KMS encryption and public-access block. Archive write/restore pending. |
| Legacy pre-shutdown inventory | [main `d55e2ab8`, run `39127113354`](https://github.com/Stuhlmuller/homelab/actions/runs/39127113354) | — | Private worker finished its full scan and matching retained baseline copies exist, but the protected workflow failed before an off-NAS object appeared. The prior [run `39119417122`](https://github.com/Stuhlmuller/homelab/actions/runs/39119417122) also failed. No baseline is accepted; old writers remain active. |
| Legacy stopped with zero writers | Pending | — | Pending |
| Full independent legacy archive/restore | Pending | — | Pending |
| Capacity and isolated canary | Pending | — | Pending |
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
