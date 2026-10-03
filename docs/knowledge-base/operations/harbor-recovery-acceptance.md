# Harbor recovery acceptance (HOME-15)

Documentary review for HOME-12 on 2026-09-29. Current activation is **unknown**;
recovery time and independent material availability are **unverified**. This
record proposes acceptance criteria for Rodman and HOME-9 leader consolidation.
It authorizes no operation and declares no outage or completed recovery.

## Evidence boundary

Local HEAD and remote main were
`a5b296da70068a666a526ff4b3656361d01157aa`. Read the
[mirror runbook](../../harbor-image-mirroring.md), [[harbor-oci]],
[[../architecture/storage-and-state]], and
[Harbor recovery contract](../../../clusters/homelab/apps/harbor/README.md#storage-and-backups).
GitHub confirmed these PRs open and unmerged; Multica's linked-PR tables were
empty, so association is by the explicit issue identifiers in their titles:

| Owner | Reviewed candidate | What it establishes |
| --- | --- | --- |
| HOME-2 | [#1113](https://github.com/Stuhlmuller/homelab/pull/1113), `66de4860068adb0c60a348c2e598e08dde415f65` | Staged independent publication, inventory and synthetic restore work; no operational Harbor recovery proof. |
| HOME-13 | [Draft #1123](https://github.com/Stuhlmuller/homelab/pull/1123), `78e4b59ae89879a87c9a45c7ec8a4d610f3cde8d` | Proposed rollback-only bundle contract and mocked outage refusals; no offline recovery implementation. |
| HOME-14 | [Draft #1124](https://github.com/Stuhlmuller/homelab/pull/1124), `365c36f613cae88fc1535f08f90c49c08a4110dc` | Independent security requirements; no approval of HOME-13 implementation or live recovery. |

Candidate contents were inspected, not merged or executed. Their authors'
reported test results are not new HOME-15 validation. No live probe, credential
read, private backup retrieval, restore or fault injection was performed.

## Activation evidence

[[harbor-oci]] records September 28 preflight and later partial publication,
ending with complete publication and node cutover pending. This is historical
documentation, not proof that mirrors remain disabled today. Merged patches,
Ready Pods and a successful publisher alone cannot establish per-node activation.

| Source-declared node | Current mirror configuration | Current fresh-fetch proof |
| --- | --- | --- |
| acer (`10.1.0.199`) | Unknown | Not supplied |
| zimaboard-0 (`10.1.0.200`) | Unknown | Not supplied |
| zimaboard-1 (`10.1.0.201`) | Unknown | Not supplied |
| zimaboard-2 (`10.1.0.202`) | Unknown | Not supplied |

Rodman must supply a sanitized, timestamped operator receipt for **each** node:
enrolled node identity and Talos version; reviewed applied SHA; persistent mirror
map and runtime `registryconfigs` comparison against that SHA (endpoints and
`skipFallback` for every registry); and the last change/rollback receipt.
Classify each node as enabled, disabled, mixed/drifted or unknown. Missing or
conflicting evidence stays unknown; never extrapolate from one worker.

To accept a completed cutover, also supply the successful protected publication
run URL/SHA and the runbook's six-file bundle equality proof when reusing an
ancestor, plus per-node initially uncached system-image pull evidence correlated
with Harbor request logs and expected digest. A cache hit is inconclusive; do
not delete caches to manufacture evidence. Share only receipt references and
sanitized results, never raw machine configs, auth headers or credentials.
Collecting new receipts or performing pulls requires the applicable separate
operator authorization; this task only inspects existing documentary evidence.

## Recovery material matrix

No row below establishes current independent availability. Historical retrieval
receipts apply only to their named artifacts and dates, not the whole recovery set.

| Material and source | Documentary evidence | Missing acceptance and existing owner |
| --- | --- | --- |
| Public bootstrap images and tools: `scripts/config/harbor-images.json`, `flake.nix`, `flake.lock`, mirror runbook | Digest inventory and upstream-first bootstrap sequence exist. Tools include pinned Talos 1.11.3. The registry cannot cold-start itself on empty nodes. | HOME-13: independently held authenticated bundle with complete executable dependencies, target platform and exact bootstrap image digests; prove retrieval/use without Harbor/GitHub. A catalog or lockfile is not stored bytes. HOME-2 owns retained artifact coverage. |
| Talos credentials, trust and node configuration: repository AGENTS.md and mirror helper | Explicit private client-file selection and source node inventory exist. | HOME-13/14: private custody receipt outside cluster/NAS, usable certificate window, enrolled identity and authenticated per-target route. No secret was opened. Worker reachability across certificate expiry/restart remains unproven. |
| Private NOFX images: `docs/nofx-private-images.md`, `scripts/config/harbor-migration.json`, current Deployment | Historical GHCR originals were retained; September 20 migration/full-pull records cover old releases. Current desired backend/frontend use Harbor release `b78cc47ddd5bb9bdace4912b47886e799a9d5efd`; subsequent builds publish directly to Harbor. | HOME-2: establish an independent complete copy of both exact current Deployment digests, their signatures/verification material and recoverable pull identity. Historical GHCR copies do not prove current digests exist there or survive a GitHub outage. Any older-version fallback needs explicit accepted loss/compatibility and GitOps approval. |
| Matched Harbor database and registry blobs: Harbor README, `postgres.yaml`, `values.yaml` | DB is local on acer; nightly 03:35 America/Los_Angeles logical dumps and registry blobs are on QNAP. Initial verified metadata dump is documented. Both NFS copies share NAS failure. | HOME-2: fence pushes/GC and relevant writers, capture DB/blobs in one consistent window, publish/retrieve exact independently stored versions, verify hashes and PostgreSQL 18/Harbor application behavior in containment. No matched independent set or full restore overlay is evidenced. |
| Harbor encryption/auth/token-signing material: Harbor README and ExternalSecrets | `/homelab/harbor/secret-key`, the full SSM contract and `harbor-token-signing` certificate/key are named. | HOME-2: privately record matching versions, independent custody and successful restoration/decryption/authentication. References in Git and a DB dump do not supply keys. Do not rotate keys as a substitute for recovery. |
| Image-signing identity: `harbor-image-signing`, `scripts/config/harbor-signing.json`, [[harbor-oci]] | Enrolled public fingerprint and historical private backup receipts are documented. Signing key is outside DB/blob backups. | HOME-2: retrieve the matching encrypted off-node recovery version and independently retained public key; restore identity before cert-manager regeneration and verify recovered artifact signatures. Historical receipts do not establish today's accessibility. This is not automatically a recovery-bundle signing authority. |
| Etcd, IaC/SSM and operator identity: [[../architecture/storage-and-state]], [[../architecture/secrets-and-identity]] | September 7 exact-version etcd S3 retrieval and a separate offline snapshot restore are documented; encrypted state and SSM references exist. | HOME-2: current exact-version access and private custody without cluster/NAS/Octelium. Etcd excludes PVC bytes and does not replace private Talos recovery material. These historical checks do not prove whole-control-plane recovery. |
| Public Harbor route and Octelium bootstrap | Mirror runbook requires public DNS/Cloudflare/Octelium. HOME-2 inventories Octelium DB, Redis/packages and root/encryption/identity dependencies. | HOME-2: independently recoverable matched application state and identity; HOME-13/14: prove route-independent worker recovery separately. A transport rollback cannot rebuild this route or the lost control plane. |

Reuse HOME-2 rather than creating a second destination or capture system.
At #1113's pinned revision, `scripts/application-backup.py` supports Octelium,
media-postgres, AFFiNE and Multica, **not Harbor**; its schedule includes only
Octelium/media and its complete-set limit is 5 GiB. Harbor's proposed 24-hour
RPO / 8-hour RTO appears in the inventory, not an implemented Harbor adapter.
Required HOME-2 extension remains coordinated capture, capacity/transfer sizing,
independent publication, key custody, versioned retrieval and isolated application
restore. Do not assume a registry fits the existing adapter or approve new costs.
HOME-3 must prove containment before any sensitive restore.

## Proposed targets and measurement

All targets require Rodman's ratification; none is measured or promised.

| Scope | Proposed target | Scope and success boundary |
| --- | --- | --- |
| One surviving worker's public upstream transport | At most 30 minutes from incident declaration, including approval and bundle retrieval | Aligns with HOME-13. Requires verified authenticated worker access, usable credentials, LAN, upstream DNS/Internet and required upstream digest availability. Ends only after full config readback, unchanged boot and a separately approved uncached digest pull prove upstream transport. |
| Full Harbor service recovery | HOME-2 proposal: RTO at most 8 hours; RPO at most 24 hours | Includes infrastructure, retrieval, matched DB/blob/key restoration, authentication and representative artifact pulls. RPO uses the consistent capture time, not upload time. Requires measured data volume/throughput and available replacement capacity; no recovery-time estimate has been established. |
| Sole-control-plane loss, NAS replacement, private-only image loss or total cold bootstrap | No accepted target | Must receive separate dependency-complete targets and evidence. Neither the 30-minute transport target nor an 8-hour Harbor proposal guarantees whole-cluster recovery. |

For a later authorized drill:

1. Approve the exact reviewed implementation/bundle digest, trust root,
   validity/revocation record, enrolled target/endpoint, mirror-only diff,
   credential reference, test image digest, operator, outage scenario and window.
   The offline path must exist and pass independent security review first.
   Define stop conditions and exclude concurrent config writers. Use an approved
   non-production target first; any production fault injection needs its own
   concrete approval. Do not run the current helper in known unsupported outages.
2. Use an independent operator clock/log outside the cluster/NAS. Record UTC
   event times and monotonic elapsed duration: incident declaration (T0), approval,
   bundle retrieval, integrity/identity checks, candidate validation, apply start,
   readback and first verified fresh pull (T1). Include approval/retrieval delays;
   do not restart the clock at apply or remove unsuccessful attempts from results.
3. Measure GitHub/DNS failure, advanced main, Harbor/public-route failure and
   unavailable `.199` separately, then in the combined declared scenario.
   Distinguish failure of GitHub/Harbor name resolution from upstream DNS, which
   transport recovery still needs. Record what was actually unavailable and how
   the approved test established it. Warm-worker success does not prove restart
   or expired-certificate recovery; record those boundaries separately.
4. Pass only when the authenticated intended node changed exactly the reviewed
   mirror map with no reboot, full persistent readback matches, and the initially
   uncached expected digest arrives through the intended upstream path with
   correlated transport evidence. Helper exit zero, Ready status, a manifest-only
   check or a cache hit is insufficient. T1 minus T0 must be at most 30 minutes.
5. Missing evidence is inconclusive and not accepted. Exceeding the target is a
   timing failure even if recovery later succeeds. Wrong identity, unintended
   diff, reboot, credential/trust failure or unavailable approved endpoint fails
   safety acceptance. Stop before mutation on preflight failure; after an apply
   timeout/readback failure, mark applied state unknown, preserve evidence and
   reconcile through authorized read-only access. Never blindly retry or advance.
6. For Harbor data recovery, record declaration, consistent capture, exact-version
   retrieval and service-acceptance times, dataset bytes and transfer duration.
   Require HOME-3 containment, replacement volumes without production mounts,
   matching DB/blob/key versions, private-project denial to anonymous callers,
   authenticated full digest pulls, expected records/blob references, and signature
   verification. Disable outbound side effects. RTO ends at application acceptance;
   RPO is declaration minus recovered capture time. No measured claim is possible
   until HOME-2 supplies its restore implementation and authorized drill receipts.

Public receipts contain only scenario, node alias, revision/bundle identifier,
approval reference, phase durations, pass/fail/unknown, dependency limits and a
private evidence reference. Keep real configs, credentials, backups and raw logs
private. Preserve old claims, blobs and retained copies. Re-enabling strict mirrors
is a separately approved activation with current-main/publication checks; there
is no automatic rollback to the outage-causing configuration.

## Proposed HOME-9 decision record

**Pending Rodman decision; recommended gate:** require an independently usable,
reviewed recovery path and the scoped operational receipts above before further
strict-mirror cutover. Current activation is unknown; do not automatically disable
or enable any node. HOME-12 operational acceptance remains open.

Alternative: Rodman explicitly accepts GitHub/current-main, sole Talos proxy and
public-route dependencies for named nodes and a stated period, with an approved
outage budget and residual private-image/data risks. No such acceptance or budget
was supplied; the proposed 30 minutes does not demonstrate existing-path recovery.
Record decision owner/date, exact revision/nodes, selected option, approved targets,
expiry/review date and receipt references in HOME-9 through leader consolidation.

HOME-13 retains implementation ownership, HOME-14 independent security review,
HOME-2 backup/capture/restore ownership and HOME-3 containment. This document adds
no service, destination, permission or live configuration. Merge/deployment,
activation/rollback, new routes, spending, secret access and real-data drills
retain their separate concrete approvals. This docs-only review does not satisfy
those gates or require approval merely to submit the proposal.
