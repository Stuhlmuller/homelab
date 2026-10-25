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
| Earlier stock controller/runtime publication | [main `3814835f`, run `39103518827`](https://github.com/Stuhlmuller/homelab/actions/runs/39103518827); controller `sha256:8d0d0565bfcc14b070d55434557704480713c97819fe80f490bc046458241164`, runtime `sha256:649351619d6a6697671ceb8bca36c8fd104ff0416e1a652095ce5de6fbf437b6` | — | Historical signed and fully pulled pair; the newer source-built bundle below supplies the selected digests. |
| Full platform image catalog and transitive render | [main `8176edde84f5b548a75eb2fbfdc7b4112db2140b`, protected `all` mirror `40172274517`](https://github.com/Stuhlmuller/homelab/actions/runs/40172274517) | — | Passed 2026-10-25 13:43 UTC for all 215 reviewed public sources: both jobs succeeded, with matching digests and complete authenticated Harbor pulls. The six strict publication-bundle files matched current main `8877b3b73f74a1d023456f46ad9510a3d88b22ed` byte for byte at acceptance. Earlier 214-image runs remain historical. |
| Source-built Enterprise controller/runtime/CLI/operator | [main `4b0186236b919570164a73f5ca3b8ef7420564cb`, protected publisher `40048058867`](https://github.com/Stuhlmuller/homelab/actions/runs/40048058867); exact refs below | — | Passed 2026-10-24 01:28 UTC: exact-main build, four complete authenticated pulls, signer public-key fingerprint check and cosign verification. Controller/runtime and CLI are pinned in source; this operator digest became historical when the selected Installation/values bytes changed. |
| Exact-source Enterprise journal operator | [main `fda0d68cd2fc5d4689b6f1b048d329ae66ef3727`, protected publisher `40056484158`](https://github.com/Stuhlmuller/homelab/actions/runs/40056484158); `sha256:f0a2f2757218ebd1e09323cb360f787794bcbbd204d0179ebc1ed553ce8e1e08` | — | Passed 2026-10-24 03:24 UTC: exact-current-main build, four complete authenticated pulls, signer public-key fingerprint check and cosign verification. The operator digest and embedded source SHA are pinned in the disabled declaration; placement, bootstrap credential and live isolation proofs remain open. |
| Pinned Prometheus one-image qualification | [main `12bb86c84beffd8a7260049fa46abb3deeefa664`, protected `prometheus` mirror `39949606211`](https://github.com/Stuhlmuller/homelab/actions/runs/39949606211); `quay.io/prometheus/prometheus:v3.11.3-distroless@sha256:cff72a3f49918f41c4b5c8a6174dd8433036bebf7878120da538b3720ba3fa0d` | — | Passed 2026-10-23 12:14 UTC: exact-current-main guard, matching digests and complete authenticated Harbor pull. This fixed one-image scope does not pass full-catalog T004. |
| LiteLLM Linux amd64 child publication | [main `0183db1c`, protected mirror run `39210811031`](https://github.com/Stuhlmuller/homelab/actions/runs/39210811031); `ghcr.io/berriai/litellm-database@sha256:2791e3241d7fa59ad942c54c237fb0d53a140b52fad2bd4b40c14a873dbc14a8` | — | Passed exact-current-main guard, source digest check, and complete authenticated Harbor pull. This one-image scope does not pass the full-catalog T004 gate. |
| Legacy off-NAS archive bucket | [main `2841475f`, protected apply `39110519607`](https://github.com/Stuhlmuller/homelab/actions/runs/39110519607) | — | Applied; read-only check confirmed versioning, KMS encryption and public-access block. Publication and separate verification restored the versioned off-NAS objects. |
| Legacy pre-shutdown inventory | [main `d55e2ab8`, run `39127113354`](https://github.com/Stuhlmuller/homelab/actions/runs/39127113354); [main `6de59d7c`, protected recovery `39142331296`](https://github.com/Stuhlmuller/homelab/actions/runs/39142331296) | `e8663e8451f7d76acfdd91904b7a9373a738ef5de44195ac4127ff862389307b` | Passed: the private success marker and both retained baseline copies match this digest; protected publication verified current source identities, one KMS-encrypted S3 version, and a versioned download matching the baseline. Old writers were active at this pre-shutdown gate; the next row records their shutdown. |
| Legacy stopped with zero writers | [main `f818b41b`, reviewed shutdown PR #1350](https://github.com/Stuhlmuller/homelab/pull/1350); Argo `openclaw` synced to that revision at 2026-10-18 16:15:52 UTC | `da89c8f5fde25808175f667767d3a46e06663e58ddb9efd2bfcc55a79ca54d2e` | Passed at 16:17 UTC: Deployment 0 desired/ready, zero gateway Pods, backup CronJob suspended with zero active Jobs, reader Ready on the expected node, and four retained PVC/PV identities verified. Private read-only status receipt retained outside Git. |
| Legacy post-shutdown inventory | [main `e48bcbe7`, run `39157724373`](https://github.com/Stuhlmuller/homelab/actions/runs/39157724373); [verification `39170006465`](https://github.com/Stuhlmuller/homelab/actions/runs/39170006465) | `cd0845fa234c374609e1196f182ac82ed525340bad2b52a21f88fee42b4e1ea4` | Full stopped-source scan, one versioned off-NAS object, matching downloaded bytes and KMS encryption verified. |
| Full independent legacy archive/restore | [source archive `39366476872`](https://github.com/Stuhlmuller/homelab/actions/runs/39366476872); [publication `9f64b56a15c8a1c1b81606e0fa751157b09f47fb/39501240221`](https://github.com/Stuhlmuller/homelab/actions/runs/39501240221); [separate verification on `90d3d413`, run `39910018168`](https://github.com/Stuhlmuller/homelab/actions/runs/39910018168) | — | Passed T013. Protected publication uploaded the versioned archive and receipt, restored both objects and wrote a private final receipt. The separate protected `verify` run succeeded on 2026-10-23 09:52 UTC after retrieving the exact published versions and independently restoring the full local/NAS trees, both SQLite databases, NAS workspace/configuration, and historical backup directories. Local source and partial attempts remain retained. |
| Legacy compatible recovery rehearsal | [read-only image/mount review on `90f7338`](https://github.com/Stuhlmuller/homelab/commit/90f733820e1c51b3b5a17c0743e606e6439a3d4c); [failed transfer attempts `39942297939`, `39951803625`, `39966041305`](https://github.com/Stuhlmuller/homelab/actions/runs/39966041305); [cancelled protected copy run `39988927652`](https://github.com/Stuhlmuller/homelab/actions/runs/39988927652); [successful protected resume on main `efb6a3a`, run `40050057926`](https://github.com/Stuhlmuller/homelab/actions/runs/40050057926); [failed protected network preflight 40207428612](https://github.com/Stuhlmuller/homelab/actions/runs/40207428612); [failed protected network preflight 40217814422](https://github.com/Stuhlmuller/homelab/actions/runs/40217814422); [registry recovery PR #1679](https://github.com/Stuhlmuller/homelab/pull/1679) | — | Partial. The first three attempts failed before a verified copy. Run `39988927652` downloaded the pinned versioned archive and receipt and started a detached restore worker, then the six-hour protected job was cancelled. Its source-bound `resume-restore` run passed exact-main, prior-job provenance and the protected legacy stage at 2026-10-24 02:04 UTC. The stage required a stable worker success marker, exact cached archive/receipt size and SHA-256, a completed restored-database report, source identity and zero stopped-production writers; it prepared a separate private NAS scratch recovery tree. Original claims and credentials remain retained; the reader mounts originals read-only. Both protected network-preflight runs passed the exact-main guard, then failed in the sanitized preflight category; neither produced a rootless capability receipt. After registry recovery merged, a read-only check found the reader 1/1 Ready, the legacy gateway 0/0, the backup CronJob suspended, and id -u inside the reader returned 1000. T014 remains open: the old image has not booted in isolation, a UID 1000 local copy and enforced offline network boundary have not been proven, six external `/app` links may depend on unretained writable-overlay contents, and three dangling external targets remain unclassified. |
| Legacy isolated restore host (T014) | [recovery boundary](../../clusters/homelab/apps/openclaw/README.md), 2026-10-25 read-only archive `stat` | — | Blocked. The retained compressed archive is 18,917,154,522 bytes, exceeding a standard `ubuntu-24.04` runner's 14 GB SSD before extraction. Select a reviewed larger isolated Linux host with measured archive, restored-root and image space before a boot rehearsal. T014 remains open. |
| Historical capacity and isolated canary | [earlier read-only checks, PR #1539](https://github.com/Stuhlmuller/homelab/pull/1539); 2026-10-25 17:48 UTC post-recovery recheck below | — | Blocked at the 2026-10-25 sample. Acer had 2,807 MiB unreserved, 1,289 MiB short of the initial 4 GiB Enterprise reservation. Suspending Langfuse and Dispatcharr would leave 1,399 MiB after that reservation, a 3 GiB Gateway burst, and one 512 MiB replacement by request arithmetic, but no complete independent restore or measured peak/restart proof exists. `zimaboard-2` hosted eight ordinary Pods at that sample, so the canary is not isolated. T022, T027 and T035 remain pending. |
| Legacy network capability retry | [guard-race run `40221941143` on `fb8b436`](https://github.com/Stuhlmuller/homelab/actions/runs/40221941143); [protected run `40450455658` on `54bcbd9`](https://github.com/Stuhlmuller/homelab/actions/runs/40450455658) | — | No T014 receipt. The former stopped at the current-main guard before credentials. The latter passed static validation, then failed in the sanitized `network-access` category in Protected Legacy Retention. Rootless capability and isolated old-image recovery remain unproved. |
| Traefik and ztunnel recovery | [signed PR #1703, merge `ff3fe008`](https://github.com/Stuhlmuller/homelab/pull/1703); 2026-10-27 18:43–18:47 UTC strict-TLS host probes and read-only Argo/Pod recheck | — | GitHub verified the merge signature. Argo `traefik` was Synced and Healthy at `ff3fe008`; its Deployment was 1/1 Ready with the Pod on `zimaboard-1`. All four node ztunnel Pods were Ready. Strict-TLS probes returned HTTPS 200 for Argo CD and an unauthenticated HTTPS 401 challenge from Harbor `/v2/`. These verify those routes, not every consumer; Enterprise network qualification remains pending. |
| Latest legacy network capability retry | [exact-main `ff3fe008`, protected run `40562837375`](https://github.com/Stuhlmuller/homelab/actions/runs/40562837375) | — | No T014 receipt. Fixed-operation validation and the protected exact-current-main guard passed; Protected Legacy Retention failed in the sanitized `network-access` category at 2026-10-27 18:57 UTC. Rootless capability and isolated old-image recovery remain unproved. |
| Legacy link classification | [protected run `40050057926`](https://github.com/Stuhlmuller/homelab/actions/runs/40050057926), private report/marker recheck | — | 37 links: 27 contained, 9 external, 1 missing in archive. Three external cache targets and the separate NAS skill target are absent. Six image targets exist lexically; old overlay and boot behavior remain unproved. T014 open. |
| 04:49 capacity sample | [read-only recheck](#october-27-capacity-rechecks) on `54bcbd9` | — | Acer was 1,201 MiB short of Enterprise's 4 GiB request budget. Pausing Langfuse and Dispatcharr would have left 1,487 MiB after modeled burst and replacement, by requests only. `zimaboard-2` had nine ordinary Pods and no isolated canary. T022, T027, T035 open. |
| Earlier capacity and isolated canary | [05:49 UTC read-only Acer recheck](#october-27-capacity-rechecks) on `99abc4f`; last full-node sample at 05:20 UTC | — | The failed Renovate Job's Pod was gone, returning Acer to 2,895 MiB request headroom, still 1,201 MiB short of Enterprise's 4 GiB budget. A Langfuse+Dispatcharr pause would leave 1,487 MiB after modeled burst/replacement, by requests only; recovery, peak and canary proof remained absent. T022, T027, T035 open. |
| Earlier capacity and isolated canary | [07:30 UTC read-only recheck](#october-27-capacity-rechecks) on `99abc4f` | — | An hourly Renovate ImagePullBackOff Job again reserved 512 MiB on Acer: 2,383 MiB free by request, 1,713 MiB short of Enterprise's 4 GiB budget. A Langfuse+Dispatcharr pause left only 975 MiB after the modeled burst/replacement while it persisted. Zima2 had 423 MiB request margin and 447 MiB physical working-set margin before the 346 MiB-request/704 MiB-limit canary. No peak, restart, recovery or isolation proof. T022, T027, T035 open. |
| Latest capacity and isolated canary | [18:47 UTC post-recovery recheck](#october-27-capacity-rechecks) on `ff3fe008` | — | Acer had 2,895 MiB request headroom, 1,201 MiB short of the initial 4 GiB Enterprise budget. Splitting components across workers still lacked safe memory and local-claim disk margin; `zimaboard-2` was not an isolated canary. The screened Langfuse+Dispatcharr pause would leave 1,487 MiB after the modeled Gateway burst and one replacement, by requests only. No service was paused or moved; recovery, peak and restart proofs remain absent. T022, T027, T035 open. |
| Talos node-by-node ladder | Pending | — | Pending |
| Istio minor ladder | Pending | — | Pending |
| Kubernetes 1.35.9 | Pending | — | Pending |
| Firewall canary and node expansion | Pending | — | Pending |
| Envoy/Gateway API private route | Pending | — | Pending |
| PostgreSQL roles/TLS and isolated restore | Pending | — | Pending |
| Private browser access source | [access PR #1420](https://github.com/Stuhlmuller/homelab/pull/1420), `bd5bd437`; [installation PR #1424](https://github.com/Stuhlmuller/homelab/pull/1424), `e24dc89` | — | Source validated: authenticated Octelium console and post-auth redirect, opaque native-host private route and DNS/certificate from #1420; cookie and trusted-proxy declarations from #1424. Live URL cutover and browser/TLS/WebSocket acceptance remain pending. |
| Protected Enterprise operations stages | [workflow](../../.github/workflows/openclaw-enterprise-operations.yml), [stage guard](../../scripts/ci/openclaw-enterprise-stage.sh), [journal dispatcher](../../scripts/ci/openclaw-enterprise-journal-operator.py), [operator source](../../clusters/homelab/apps/openclaw-enterprise-operator/README.md) | — | Source-only. Fixed dispatch is guarded and serialized; full-sync blocks on the unselected installation phase. Reconcile, stop, verification and binding use source-bound in-cluster Jobs. Before binding Job creation, the runner verifies the immutable reviewed startup Secret and pins its UID/resource version and candidate digest in the Pod template. The Job reads the private bootstrap key from a read-only PVC mount and hands a bounded proof to the protected runner for an exact-main, UID/resourceVersion-guarded startup Secret patch, followed by in-cluster verification. The operator remains disabled without verified placement, PV/image identities, bootstrap key ownership or enforced network policy. A fixed source-only cleanup stage for a terminal failed pre-patch Job now requires the historical source/run/attempt, exact Job/Pod UIDs, the exact immutable mounted ConfigMap, unchanged unbound Secret witness and retained PVC/PV identities before one preconditioned foreground Job delete; uncertain outcomes require readback. It has not been dispatched or proven live. A committed Secret patch with failed post-patch proof needs separate reviewed recovery; pre-patch cleanup cannot handle it. Restore and acceptance remain blocked; T041/T043 and live outcomes remain pending. |
| Recovery failure fixtures (T050) | [recovery test](../../scripts/ci/openclaw-enterprise-recovery-test.py), [static gate](../../scripts/ci/static-checks.sh) | — | Source-only: 12 tests passed in the Nix development shell on 2026-10-25. They cover native stop ordering, lost/uncertain termination, retained new and legacy state, PVC retention, blocked enforcement removal and incomplete backup material. T054 orchestration and live restore remain pending. |
| Scheduled complete new-state backup (T051) | [backup script](../../clusters/homelab/apps/openclaw-enterprise-foundation/backup.sh), [pinned Agent stop contract](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/reference/agents.md#L328-L334), [pinned recovery guide](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/guides/deploy/production-handoff.md#L108-L130) | — | Pending: no identity-checked producer across the separate operator/Agent PVC namespaces, tenant Secret value capture, in-cluster credential/protected publication path, or encrypted off-node mount. Supported stop clears the active revision and resume needs a new deployment; upstream has no general backup command and rejects live SQLite/PVC copies. At 2026-10-25 12:41 UTC, read-only `kubectl api-resources --api-group=snapshot.storage.k8s.io` returned no resources, so no VolumeSnapshotClass is available for an online snapshot path. No scheduled capture or independent restore receipt. |
| Complete new-state recovery material (T049/T051) | [foundation recovery boundary](../../clusters/homelab/apps/openclaw-enterprise-foundation/README.md), [packager](../../clusters/homelab/apps/openclaw-enterprise-foundation/backup.sh), [restore fixture](../../clusters/homelab/apps/openclaw-enterprise-foundation/restore-drill.yaml) | — | Blocked. The packager has no producer for the pinned chart's two bootstrap PVC files, the OCE-owned tenant Agent claim, tenant Secrets and metadata, operator journal, or gateway TLS material. No declared writer fence, encrypted off-node publisher, or complete isolated service restore exists. T049/T051 have no acceptance receipt. |
| Enterprise install and hook failure matrix | Pending | — | Pending |
| Inactive agent reconciliation and retry | Pending | — | Pending |
| Model credential and real provider probe | Pending | — | Pending |
| Browser, native origin and network denials | Pending | — | Pending |
| Complete new-state independent restore | Pending | — | Pending |
| 24-hour observation and selective retirement | Pending | — | Pending |
| T059 source documentation and OpenWiki refresh | [merged PR #1560](https://github.com/Stuhlmuller/homelab/pull/1560), main `0e223d6`; protected static, lint, image-policy, network-policy and release-dry-run checks passed | — | Passed for source documentation only: five named runbooks updated and affected OpenWiki pages refreshed by the native update path. Capacity, credentials, policy enforcement, platform upgrades and Enterprise live acceptance remain pending. |

A 2026-10-25 read-only check of the private restored link report found 37
links: 27 contained, nine external, and one pointing to a missing target
within the archived roots.
Six external `/app` links resolve to five nonempty directories in the pinned
image, but the former writable overlay is unproven. Three workspace links
point under `/home`; the fresh reader has no targets there, and the old Pod
declared no `/home` volume, so their former dependency is unknown. The one
NAS-contained skill link is absent from both archive and original read-only
mount while its source link matches; it was already dangling, not omitted
by archival. Its purpose remains unknown. This classification does not
prove an isolated compatible startup or pass T014.

T051 NFS option remains unqualified. On 2026-10-25, read-only
`df -B1 /var/lib/postgresql/data` inside the NFS-backed
`octelium-postgres-0` Pod reported 718,305,492,992 bytes available on the
QNAP `/homelab` export. [NFS claim sizes](../storage-nfs.md) do not reserve
or cap that space, so this sample does not admit retention. The current
[packager](../../clusters/homelab/apps/openclaw-enterprise-foundation/backup.sh)
writes its dump and recovery material in plaintext to `/backup` before
rename. NFSv3 `sec=sys` does not encrypt transport, QNAP at-rest encryption is
unverified, and the same NAS is not an independent off-NAS copy. Encrypt before
the first NFS write, then prove an isolated decrypt-and-restore.

The 215-image public catalog passed protected `image_scope=all` run
[`40172274517`](https://github.com/Stuhlmuller/homelab/actions/runs/40172274517).
Both jobs succeeded and its final marker confirms matching digests and complete
authenticated Harbor pulls. At acceptance, these six publication-bundle files
matched main `8877b3b73f74a1d023456f46ad9510a3d88b22ed` byte for byte:
`scripts/config/harbor-images.json`, `.github/workflows/harbor-mirror.yml`,
`scripts/ci/harbor-publish.sh`, `scripts/ci/install-kubeconfig.sh`, `flake.nix`
and `flake.lock`. T004 remains open until the changed Enterprise operator source
has a new signed, authenticated-pull publication and pinned digest.

The successful Enterprise bundle's [job summary](https://github.com/Stuhlmuller/homelab/actions/runs/40048058867#summary-120734188450) records these immutable references:

```text
harbor.stinkyboi.com/homelab/homelab-oce-controller:homelab-4b0186236b919570164a73f5ca3b8ef7420564cb@sha256:b3de708695efcd5797c188912085dc46bb1408fa320d8f4fa03db4f2a45a06b2
harbor.stinkyboi.com/homelab/homelab-oce-runtime:homelab-4b0186236b919570164a73f5ca3b8ef7420564cb@sha256:b8ddf3ad1f70a524e99392bbbc93bcd38a2b7ef640b76ed1552f432ce25a01e1
harbor.stinkyboi.com/homelab/homelab-oce-cli:homelab-4b0186236b919570164a73f5ca3b8ef7420564cb@sha256:9d77fddb3f099f329494910609459e7bc8076d74ab797ca3382fe80edf9f12d2
harbor.stinkyboi.com/homelab/homelab-oce-operator:homelab-4b0186236b919570164a73f5ca3b8ef7420564cb@sha256:ec9bb06fccb2a4b268d4af3c0a11e5686dc8f6063a807e80e27fd61342914b19
```

The first four-image attempt
[40046894679](https://github.com/Stuhlmuller/homelab/actions/runs/40046894679)
failed at fixed `authenticated-pull-controller` after upload; it produced no
signed bundle receipt. The successful retry passed that pull and all later
gates. Earlier full-catalog runs
[39953746696](https://github.com/Stuhlmuller/homelab/actions/runs/39953746696)
and [39968117747](https://github.com/Stuhlmuller/homelab/actions/runs/39968117747)
failed at item 79/214 (`authenticated-pull` / `transport-retries-exhausted`,
five OCI-index attempts) and item 207/214 (`destination-copy` /
`transport-failed`), respectively. Partial copies did not pass T004. The
selected Installation and values bytes differ from those embedded in the
earlier operator image. An exact-source rebuild on
[main `fda0d68`, run `40056484158`](https://github.com/Stuhlmuller/homelab/actions/runs/40056484158)
passed all four authenticated pulls and signature checks. Its [job summary](https://github.com/Stuhlmuller/homelab/actions/runs/40056484158#summary-120760493142)
records the operator as
`harbor.stinkyboi.com/homelab/homelab-oce-operator:homelab-fda0d68cd2fc5d4689b6f1b048d329ae66ef3727@sha256:f0a2f2757218ebd1e09323cb360f787794bcbbd204d0179ebc1ed553ce8e1e08`.
The first exact-source attempt
[40055163032](https://github.com/Stuhlmuller/homelab/actions/runs/40055163032)
failed at fixed `push-runtime` before a complete receipt. Only the successful
retry supplies the selected disabled operator image. Activation remains disabled.

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
The pinned Octelium installer constructs the Genesis image from package and
version for both init and upgrade; it has no image or digest override. A
corrected generator therefore also needs reviewed immutable image selection
in the installer path. The source catalog does not prove all live or dynamic
Octelium upstreams or Cordium Workspace outbound needs, so no narrower
generated egress rule has been selected or deployed.
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

The [Crossplane source](../../IaC/homelab/us-west-2/apps/platform-crossplane/stack.hcl) declares
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

At 2026-10-25 10:57–10:58 UTC with repository `main` at `1e46ec59`, read-only
`kubectl get nodes -o json`, `kubectl get pods -A -o json`,
`kubectl top nodes`, per-node kubelet `/stats/summary`, and targeted
`kubectl top pods -n <namespace>` found all
four nodes Ready and untainted:

| Node | Memory requested / allocatable | Memory used | Root filesystem free |
| --- | ---: | ---: | ---: |
| `acer` | 14,099 / 15,261 MiB | 11,725 MiB | 382.08 GiB |
| `zimaboard-0` | 7,148 / 7,282 MiB | 6,341 MiB | 4.98 GiB |
| `zimaboard-1` | 3,372 / 7,282 MiB | 5,953 MiB | 8.98 GiB |
| `zimaboard-2` | 1,078 / 1,308 MiB | 960 MiB | 8.65 GiB |

A 12:07 UTC read-only refresh found all nodes Ready without MemoryPressure or
DiskPressure. `kubectl describe node`, `kubectl top nodes`, and kubelet
`/stats/summary` gave the following then-current values; they are samples, not
historical peaks:

| Node | Memory requested / allocatable | Memory used | Root filesystem free |
| --- | ---: | ---: | ---: |
| `acer` | 14,099 / 15,261 MiB | 11,693 MiB | 382.09 GiB |
| `zimaboard-0` | 7,276 / 7,282 MiB | 5,547 MiB | 5.00 GiB |
| `zimaboard-1` | 3,884 / 7,282 MiB | 6,141 MiB | 8.96 GiB |
| `zimaboard-2` | 1,078 / 1,308 MiB | 967 MiB | 8.64 GiB |

At 2026-10-25 12:50 UTC, kubelet reported 8.98 GiB free on
`zimaboard-1`, below one required 10 GiB local Enterprise claim before
image pulls or restart margin. Kubernetes reported seven bound node-local
volumes there: three retained legacy OpenClaw volumes (5 + 3 + 2 GiB),
Mastodon PostgreSQL and Redis (3 + 1 GiB), and two Cordium workspaces
(20,000 + 10,000 MiB). Authenticated read-only Talos `usage` measured 300 MB
in `/var/lib/openclaw-runtime`, 66 MB in Mastodon PostgreSQL, 4.1 MB in
Mastodon Redis, and 438 kB across the Cordium workspaces. Their combined
occupancy is below 0.35 GiB, less than the 1.02 GiB minimum claim shortfall;
the declared PV capacities are not measured disk use. Retiring these services
cannot close the shortfall and would discard retained state.
The CRI lists 135 images with 13.9 GB summed listed sizes, but shared layers
and active images make that sum no verified reclaim amount. No reviewed
selective image-cleanup receipt exists. `acer` was the only measured
local-storage candidate.

At 14:40 UTC, with `main` at `46476e7d`, Traefik had zero ready replicas and
its Pod was in `ImagePullBackOff`. Read-only node requests were 12,198 / 15,261
MiB on `acer`, 5,716 / 7,282 MiB on `zimaboard-1`, and 1,020 / 1,308 MiB on
`zimaboard-2`. Grafana's 768 MiB Pod was running on `zimaboard-1`, so pausing
it would release no `acer` request in this observed placement. `zimaboard-2`
also hosted LiteLLM, CoreDNS, Tailscale operator and two pending cert-manager
Pods; `kubectl top nodes` sampled it at 1,289 MiB used. This outage-affected
layout is not safe new headroom. All retirement margins and the earlier
four-Pod canary model below describe the pre-outage placement only. The
post-recovery sample below supersedes that arithmetic for current screening.

The two 10 GiB local claims put PostgreSQL (512 MiB request) and the
Embedded Gateway (1,792 MiB request) on `acer` under the proposed storage
pattern. Suspending only Dispatcharr releases 1,664 MiB there, leaving 522
MiB after that 2,304 MiB floor. API, worker, and Envoy have a further 1,792
MiB planning reservation. They fit `zimaboard-1` by request (5,676 / 7,282
MiB), but consuming that reservation atop its then-measured 6,141 MiB working
set gives 7,933 MiB, 651 MiB above allocatable before peaks. Putting one 512 MiB
component on `acer` leaves only 10 MiB by request, while the other 1,280 MiB
would put `zimaboard-1` at 7,421 MiB using the same estimate. The other
workers have no admission headroom or 10 GiB local-claim space.

Suspending only Langfuse releases 2,816 MiB on `acer` and vacates its
`zimaboard-2` PostgreSQL Pod. Placing PostgreSQL, Gateway, API, and worker on
`acer` would leave only 650 MiB by request; Envoy's 768 MiB planning budget
on `zimaboard-1` leaves 373 MiB against its sampled working set. Relocating
`zimaboard-2`'s three remaining ordinary Pods there adds 244 MiB of observed
use and reduces that estimate to 129 MiB before startup or rolling overlap.
Neither one-service split is an admitted placement.

The operator ruled out hardware upgrades and requested service retirements.
A source-only retirement candidate would **suspend**, not delete, all five
Langfuse Pods and both Dispatcharr Pods while retaining their claims and
credentials. This releases 2,816 + 1,664 = 4,480 MiB of requests on `acer`.
Its 1,162 MiB baseline margin would become 5,642 MiB; an Acer-only 4,096 MiB
Enterprise planning budget would leave 1,546 MiB before startup, backup,
rolling replacement, policy enforcement, and peak margin. The Gateway's 3 GiB
limit alone permits 1,280 MiB above its request, reducing that margin to 266
MiB before any other burst. This pair has more static margin than the other
two-service candidate assessed, not proof of safe admission. Suspending
Langfuse and Mastodon instead would leave 1,034 MiB after the same Enterprise
reservation and interrupt a public app. The proposed 10 GiB
PostgreSQL and 10 GiB Embedded Gateway claims, plus 1 GiB bootstrap and 1 GiB
journal claims, could use `acer`'s disk in principle; the separate 24 GiB
restore scratch also needs admission. T035 has not created or bound those
node-affine volumes. The current [profile input](../../clusters/homelab/apps/openclaw-enterprise/profile-input.json)
pins control Pods to `oce-role: control` but the Embedded Gateway to
`oce-role: agents`; its Dedicated-only `gatewayNodeSelector` does not fix
co-location. A reviewed selector change is required before Acer-only placement.

If Langfuse is suspended, `zimaboard-2` loses its 128 MiB PostgreSQL Pod.
The remaining three ordinary Pods have no required node selector: Multica
frontend 320 MiB, Cloudflare connector 64 MiB, and Harbor vulnerability
exporter 32 MiB. Moving those 416 MiB by reviewed placement to `zimaboard-1`
would leave that node about 2,982 MiB unreserved by request; its then-measured
usage plus those Pods' observed 244 MiB is about 6,385 / 7,282 MiB before
peaks or rolling overlap. The vacated `zimaboard-2` would retain 534 MiB of
system requests; a proposed 250 MiB enforcer plus three 32 MiB fixtures
would leave 428 MiB unreserved. Its then-measured usage minus those four Pods' 293
MiB, plus the 346 MiB proposed canary requests, is about 1,020 / 1,308 MiB.
Neither estimate proves transient fit, image-pull disk headroom, or isolation;
a `NoSchedule` taint does not evict existing Pods.

At 2026-10-25 12:23 UTC, `kubectl top nodes` sampled `acer` at 11,881 MiB,
`zimaboard-1` at 6,561 MiB and `zimaboard-2` at 966 MiB. Recent `acer`
samples ranged from 11,693 to 11,952 MiB, a 259 MiB spread; this is not a
peak measurement. The pinned upstream [Gateway renderer][gateway-recreate]
sets `Recreate`, so a second Gateway Pod is not part of this calculation;
verify that the eventual controller image still contains this behavior.
For screening, reserve 512 MiB for one API or worker replacement plus another
512 MiB, roughly twice that sampled spread. This 1 GiB post-Gateway-burst
floor is a planning filter, not measured peak or rollout acceptance. A stricter
1 GiB residual after the Gateway burst and replacement needs more capacity.

<!-- markdownlint-disable-next-line MD013 -->
[gateway-recreate]: https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/apps/controller/src/drivers/compute/kubernetes/index.ts#L14668-L14673

<!-- markdownlint-disable MD013 -->

| Additional pause after Langfuse + Dispatcharr | Acer free after 4 GiB Enterprise reservation | After Gateway reaches 3 GiB and one 512 MiB replacement | Effect and recovery gate |
| --- | ---: | ---: | --- |
| None | 1,546 MiB | -246 MiB | Cannot fit the screened replacement. |
| Multica runtime (512 MiB) | 2,058 MiB | 266 MiB | Below the 512 MiB residual floor; local session/credential state has no approved loss path. |
| Grafana (768 MiB) | 2,314 MiB | 522 MiB | Barely clears the filter but loses dashboards and Grafana-managed alerts; its SQLite/PVC state lacks a verified independent restore. |
| Mastodon, including its three Acer Pods (1,152 MiB) | 2,698 MiB | 906 MiB | Public service outage; local PostgreSQL/Redis, NFS media, application keys and a database-only NAS backup lack a complete independent restore. |
| Multica runtime + Grafana (1,280 MiB) | 2,826 MiB | 1,034 MiB | Clears the illustrative 1 GiB residual screen but also stops the agent daemon and monitoring; neither retained state has a verified independent restore. |

<!-- markdownlint-enable MD013 -->

The Grafana row assumes all three remaining ordinary `zimaboard-2` Pods move
to `zimaboard-1`: their sampled 247 MiB would raise that node to 6,808 / 7,282
MiB, leaving 474 MiB before peaks. For the Mastodon row, moving Multica
frontend to `acer` consumes 320 MiB of its request margin, leaving 586 MiB
after the screened replacement; moving Cloudflared and Harbor exporter to
`zimaboard-1` adds 74 MiB sampled use there, leaving 647 MiB. Neither
allocation proves service continuity or safe restart headroom.

The canary is independently blocked. At 2026-10-25 12:56 UTC, the kubelet
Summary API reported a 955 MiB node working set on `zimaboard-2`; its four
ordinary Pods used 297 MiB. The Node API reports 1,792 MiB physical capacity
and 1,308 MiB allocatable. If those Pods leave and the [enforcer](../../clusters/homelab/platform/network-policy/daemonset.yaml)
and three simultaneous [fixtures](../../clusters/homelab/platform/network-policy/canary/fixtures.yaml)
reach their 512 + 192 MiB limits, projected node use is 955 - 297 + 704 =
1,362 MiB, about 430 MiB below physical capacity. The earlier comparison to
1,308 MiB was too strict: [Node Allocatable](https://kubernetes.io/docs/tasks/administer-cluster/reserve-compute-resources/)
is the Pod budget, while the node working set includes host use. Separately,
534 MiB system Pod requests plus 250 + 3 × 32 MiB new requests leave 428 MiB
under allocatable. These snapshots do not measure enforcer peaks, host growth,
restart overlap, image-pull space or cleanup. No reviewed placement has vacated
the node; keep T022 and T027 blocked.

Suspension would interrupt Dispatcharr's IPTV/EPG export and Langfuse's
telemetry UI/ingestion; [LiteLLM](../../clusters/homelab/apps/litellm/README.md)
still requires Langfuse-attributed caller traces for its acceptance checks.
Before relying on this capacity release, qualify caller behavior and complete
the [recovery contracts](../application-recovery.md): Langfuse needs coordinated
PostgreSQL, ClickHouse, Valkey and raw-event S3 recovery plus encryption/salt
secrets and a queue-loss decision. An October 25 read-only inventory found
4,683,189,334 bytes of active ClickHouse parts and 827,069,112 bytes across
1,857 Langfuse blob-bucket versions. Those alone exceed the 5 GiB whole-set
limit in [`application-backup.py`](../../scripts/application-backup.py).
The [blob IAM policy](../../IaC/terragrunt-catalog/modules/aws-langfuse-blob-storage/main.tf)
lacks `ListBucketVersions` and `GetObjectVersion`; an exact independent copy
needs a reviewed scoped grant and componentized publication. Dispatcharr needs
a paired PostgreSQL and runtime-files set plus private provider credentials.
Draft #1666 keeps its one-shot capture Job outside active GitOps. Including it
would create the Job before a separate checker could prove a continuous writer
fence; its commit-shaped `FENCE_REF` and pre/post Pod snapshots alone cannot
exclude a transient writer. A protected capture path still needs a reviewed
start gate, continuous Pod observation or equivalent durable audit through the
capture window, exact Argo revision and Deployment identity/generation, both
source PVC/PV identities, and a completed Job bound to an off-host checksummed
manifest. No such fence receipt, approved backup-host mount, or offsite copy
exists, so the paired publisher must keep rejecting Dispatcharr.
Retained PVCs make a declarative pause reversible but are not independent
backups. No suspension,
relocation, taint, local claim, or permanent retirement is authorized by this
review; T022, T027 and T035 stay open.

## Historical post-Traefik recovery capacity recheck

The October 25 screen below is superseded by the October 27 recheck.

At 2026-10-25 17:48–17:50 UTC with `main` at `ab28b8d1`, read-only node
description, Pod JSON, Metrics Server, and kubelet Summary API checks found
Traefik 1/1 Ready. All four nodes were Ready, untainted, and reported no memory,
disk, PID, or network pressure. Memory-use values are one working-set sample,
not peaks; root free space is actual kubelet filesystem availability, not PV
declared capacity.

| Node | Memory requested / allocatable | Memory used | Root filesystem free |
| --- | ---: | ---: | ---: |
| `acer` | 12,454 / 15,261 MiB | 11,374 MiB | 383.23 GiB |
| `zimaboard-0` | 7,211 / 7,282 MiB | 6,035 MiB | 11.15 GiB |
| `zimaboard-1` | 5,332 / 7,282 MiB | 5,616 MiB | 5.66 GiB |
| `zimaboard-2` | 701 / 1,308 MiB | 1,353 MiB | 8.53 GiB |

`acer` has 2,807 MiB unreserved by request, 1,289 MiB short of the initial
4,096 MiB Enterprise planning budget. It is the only measured node with room
for both separate 10 GiB local PostgreSQL and Gateway claims plus the other
planned state. `zimaboard-0` has only 71 MiB request headroom despite 11.15 GiB
disk free; `zimaboard-1` and `zimaboard-2` cannot fit even one 10 GiB local
claim in their measured root free space. No cleanup or smaller claim is
approved by this sample.

At that sample, `acer` placement gave Langfuse web, worker and ClickHouse
2,816 MiB of requests and Dispatcharr app/Celery/Redis 1,664 MiB. Langfuse
PostgreSQL and Dispatcharr PostgreSQL ran on `zimaboard-1`; Langfuse Valkey ran
on `zimaboard-0`. Grafana's 768 MiB Pod also ran on `zimaboard-1`, so pausing it
would release no `acer` request. Mastodon's three `acer` Pods requested 1,152
MiB; Multica runtime requested 512 MiB there. The table screens reversible
pauses only; it does not authorize them or release their retained state.

<!-- markdownlint-disable MD013 -->

| Reversible pause | Acer free after 4,096 MiB Enterprise reservation | After Gateway's 1,280 MiB burst above request and one 512 MiB replacement | User-visible and recovery impact |
| --- | ---: | ---: | --- |
| None | -1,289 MiB | -3,081 MiB | Enterprise does not fit its planning requests. |
| Dispatcharr only | 375 MiB | -1,417 MiB | IPTV/EPG export stops; paired PostgreSQL/files/credential restore has no receipt. |
| Langfuse only | 1,527 MiB | -265 MiB | Telemetry UI/ingestion stops; full PostgreSQL/ClickHouse/Valkey/S3 restore has no receipt. |
| Langfuse + Mastodon | 2,679 MiB | 887 MiB | Public Mastodon stops; its completed NAS database restore Job does not cover Redis, media, keys or offsite recovery. |
| Langfuse + Dispatcharr | 3,191 MiB | 1,399 MiB | Smallest screened pair above the illustrative 1 GiB residual request filter; stops telemetry and IPTV/EPG. |

<!-- markdownlint-enable MD013 -->

The Langfuse PostgreSQL checkpoint and isolated restore cover only that
database. [Raw-version inventory PR #1667](https://github.com/Stuhlmuller/homelab/pull/1667)
is draft; coordinated ClickHouse, Valkey, raw S3 version, secret and caller
recovery is unproved. [Dispatcharr publisher PR #1657](https://github.com/Stuhlmuller/homelab/pull/1657)
has merged, while [capture PR #1666](https://github.com/Stuhlmuller/homelab/pull/1666)
is draft and excluded from active GitOps. They have no stopped-writer,
offsite publication, private-credential or independent restore receipt. The
completed Mastodon backup and isolated restore Jobs cover the NAS PostgreSQL
dump only; Grafana and Multica runtime still lack complete independent restores.
Preserve each claim and credential until its actual recovery scope is proven.

At that sample, `zimaboard-2` had 607 MiB unreserved by Pod requests, but its
1,353 MiB node working set included host use and must be compared with 1,792
MiB physical capacity, not its 1,308 MiB Pod allocatable. Eight ordinary Pods
there used about 737 MiB in the sampled container metrics, including a
LiteLLM Pod at 482 MiB with no memory request. Adding the proposed enforcer
and three fixtures at their combined 704 MiB limits without moving those Pods
would exceed physical capacity by about 265 MiB. Vacating all eight by
reviewed placement would leave roughly 472 MiB physical margin at those
limits in this static screen; it would also move DNS, certificate, access and
inference components, whose placement and restart effects are unproved. A
`NoSchedule` taint alone would leave those Pods in place. The
Langfuse/Dispatcharr pause would not have vacated
`zimaboard-2` in that layout. Recheck every node and the exact
backup/restore path after any reviewed placement change; keep T022, T027 and
T035 blocked until measured peaks, restart overlap and enforced isolation pass.

## October 27 capacity rechecks

At 2026-10-27 04:49 UTC on `main` `54bcbd9`, read-only node description,
Pod JSON, Metrics Server and kubelet Summary API checks found all four nodes
Ready without memory or disk pressure. The observed memory values are one
working-set sample, not peaks; root free space is not allocated PV capacity.

| Node | Memory requested / allocatable | Memory used | Root filesystem free |
| --- | ---: | ---: | ---: |
| `acer` | 12,366 / 15,261 MiB | 10,781 MiB | 382.44 GiB |
| `zimaboard-0` | 6,635 / 7,282 MiB | 5,516 MiB | 11.17 GiB |
| `zimaboard-1` | 5,908 / 7,282 MiB | 5,637 MiB | 8.26 GiB |
| `zimaboard-2` | 885 / 1,308 MiB | 1,329 MiB | 7.43 GiB |

At that sample, `acer` had 2,895 MiB request headroom, 1,201 MiB short of the
4,096 MiB Enterprise planning budget. Its Langfuse web, worker and ClickHouse
Pods requested 2,816 MiB; the Dispatcharr app/Celery/Redis Pod requested 1,664
MiB. Pausing both would have left 3,279 MiB after that budget, then 1,487 MiB
after the modeled 1,280 MiB Gateway burst and one 512 MiB replacement. This
request arithmetic did not prove peak, restart or recovery safety. Neither
service had a complete coordinated offsite backup and independent restore.

`zimaboard-2` had 423 MiB request headroom and nine running ordinary Pods,
including LiteLLM, DNS, certificate, metrics and access components. Its
1,329 MiB observed node working set included host use and left 463 MiB
below its 1,792 MiB physical capacity. The proposed enforcer and fixtures
were not isolated there. Neither the Langfuse/Dispatcharr pause nor a
`NoSchedule` taint would have vacated those Pods.

At 2026-10-27 05:20:34–05:20:35 UTC on `main` `99abc4f`, a second read-only
node, Pod, Metrics Server and kubelet Summary API sample found:

| Node | Memory requested / allocatable | Memory used | Root filesystem free |
| --- | ---: | ---: | ---: |
| `acer` | 12,878 / 15,261 MiB | 10,476 MiB | 382.39 GiB |
| `zimaboard-0` | 6,507 / 7,282 MiB | 5,521 MiB | 11.17 GiB |
| `zimaboard-1` | 5,908 / 7,282 MiB | 5,689 MiB | 8.26 GiB |
| `zimaboard-2` | 885 / 1,308 MiB | 1,338 MiB | 7.43 GiB |

An hourly Renovate Job Pod, scheduled to `acer` and Pending in
`ImagePullBackOff`, requests 512 MiB. Its scheduler reservation reduced Acer's
headroom from 2,895 to 2,383 MiB even though the container had not started.
That is 1,713 MiB short of Enterprise's 4,096 MiB planning budget. Pausing
Langfuse and Dispatcharr would leave 975 MiB after that budget, the modeled
1,280 MiB Gateway burst and one 512 MiB replacement; this falls below the
illustrative 1 GiB residual filter. The Job may clear, so remeasure before
admission rather than treating either sample as a durable allocation.
The Pod's read-only event stream included a registry transport
`connection refused` error; Harbor and Traefik Deployment readiness does not
prove this pull route.

At 2026-10-27 05:49 UTC on the same `main` revision, the Renovate Job reported
one failure and its Pending Pod was absent. `kubectl describe node acer` then
showed 12,366 / 15,261 MiB requested / allocatable, restoring 2,895 MiB
request headroom; `kubectl top node` observed 10,928 MiB used. The hypothetical
Langfuse+Dispatcharr pause returned to a 1,487 MiB residual after the same
Enterprise budget, Gateway burst and replacement assumptions. This clears the
illustrative 1 GiB request filter at that instant but supplies no measured
peak, restart-overlap, whole-service restore or isolated-canary proof. The
hourly Job is still scheduled, so this reservation can recur.

`zimaboard-2` still has only 423 MiB request headroom and 7.43 GiB root free,
short of one proposed 10 GiB local claim. Its 1,338 MiB observed node working
set leaves 454 MiB below physical capacity, not an isolated canary margin.
No service was paused or moved. None of the screened Acer pause candidates
has a complete independent whole-service offsite restore. T022, T027 and
T035 remain open.

At 2026-10-27 07:30 UTC on the same `main` revision, a fresh read-only
node/Pod, Metrics Server and kubelet filesystem sample found:

| Node | Memory requested / allocatable | Memory used | Root filesystem free |
| --- | ---: | ---: | ---: |
| `acer` | 12,878 / 15,261 MiB | 10,382 MiB | 382.39 GiB |
| `zimaboard-0` | 6,635 / 7,282 MiB | 5,472 MiB | 11.17 GiB |
| `zimaboard-1` | 5,908 / 7,282 MiB | 6,076 MiB | 8.26 GiB |
| `zimaboard-2` | 885 / 1,308 MiB | 1,345 MiB | 7.43 GiB |

Another hourly Renovate Job started at 07:00 UTC and remained active in
`ImagePullBackOff`, reserving 512 MiB on `acer` until its 40-minute active
deadline or earlier completion. Acer's 2,383 MiB current request margin is
1,713 MiB short of Enterprise's 4,096 MiB budget. If that Job leaves and no
other Pod moves, the margin returns to 2,895 MiB, still 1,201 MiB short.
Current Acer placement has 2,816 MiB of Langfuse, 1,664 MiB of Dispatcharr,
1,152 MiB of Mastodon and 512 MiB of Multica runtime requests. Grafana is on
`zimaboard-1` and releases no Acer request if paused. No verified stateless
single-service pause covers even the stable 1,201 MiB deficit.

Hypothetically pausing Langfuse and Dispatcharr would leave 2,767 MiB on
`acer` after Enterprise's 4 GiB reservation, or 975 MiB after the modeled
1,280 MiB Gateway burst and one 512 MiB replacement while Renovate is
scheduled. Both applications lack complete independent whole-service restores;
the calculation proves no safe suspension, peak or restart fit. On
`zimaboard-2`, the proposed enforcer plus three fixtures add 346 MiB requests
and 704 MiB limits. Its 423 MiB request margin would fall to 77 MiB; the
current 1,345 MiB node working set leaves 447 MiB under 1,792 MiB physical
capacity, 257 MiB less than those fixture limits before any existing Pod grows.
The ordinary 32 MiB Harbor exporter is the only material non-system request
there. A taint alone would not evict current Pods, and no reviewed placement
frees restart and limit headroom. T022, T027 and T035 remain open.

At 2026-10-27 18:47 UTC after signed #1703 merged as `ff3fe008`, a read-only
post-recovery check found `acer` at 12,366 / 15,261 MiB requested /
allocatable: 2,895 MiB unreserved, or 1,201 MiB short of the initial 4,096
MiB Enterprise request budget. The other workers still lacked a safe split
across memory headroom and the separate 10 GiB local PostgreSQL and Gateway
claims. `zimaboard-2` still hosted unrelated Pods and did not qualify as an
isolated network-policy canary.

By requests, pausing both Langfuse (2,816 MiB on `acer`) and Dispatcharr
(1,664 MiB) would yield 2,895 + 2,816 + 1,664 - 4,096 = 3,279 MiB after
the Enterprise budget. The modeled 1,280 MiB Gateway burst above request and
one 512 MiB replacement reduce that to 1,487 MiB. These are static planning
numbers, not measured peak, restart or recovery proof. Neither service has a
complete independent whole-service restore. No pause, placement or canary
activation occurred; T022, T027 and T035 remain open.

Relevant source or policy changes invalidate affected receipts. Keep the
strict broad-egress finding for stock Enterprise public TCP/443 visible during
network acceptance; it is an accepted scoped limitation, not proof of global
destination filtering.
