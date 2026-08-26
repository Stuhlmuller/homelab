# Continuous Improvement

Tags: #operations #security #reliability #stewardship

Source: `AGENTS.md`

This homelab should improve continuously through small, reviewable changes.
Agents should treat it as home turf: notice weak assumptions, hardening
opportunities, reliability gaps, missing validation, and operational friction
before they become incidents.

## Stewardship Loop

1. Start from source-backed context: relevant code, runbooks, knowledge-base
   notes, and read-only live inspection when the question depends on current
   cluster reality.
2. Prefer repo-owned desired state over manual repair. Express fixes in
   Terragrunt, OpenTofu, Helm values, Kustomize/manifests, scripts, or docs
   before any rollout.
3. Keep improvements small enough to review. Security and reliability work is
   better as a steady stream of scoped PRs than a rare sweeping rewrite.
4. Validate with the smallest gate that proves the change, then record any
   unavailable validation plainly.
5. Update this vault whenever a finding, decision, source path, risk, or
   follow-up matters beyond the current chat.
6. Own PR follow-through for Claw-authored work: push the branch, open the PR,
   monitor required checks, resolve merge blockers, and merge when repository
   policy allows. PR creation is not the finish line.
7. Use Conventional Commits for Claw-authored commit messages and PR titles so
   release automation and reviewers can classify changes consistently.

## Finding Format

Record findings in the most specific affected note when one exists. Use this
page for cross-cutting or not-yet-owned findings.

- **Status:** open, planned, fixed, accepted risk, or obsolete.
- **Area:** workload, platform service, Talos, networking, storage, CI/CD,
  secrets, observability, or agent runtime.
- **Evidence:** source path, command, PR, or read-only observation.
- **Risk:** what could fail, leak, drift, or become hard to operate.
- **Next step:** concrete repo-owned action or validation gate.

## Current Standing Order

Rodman asked Claw to continue making security and reliability improvements as
needed, to treat the homelab as home, and to mark findings in
`docs/knowledge-base/`. This page is the durable capture point for that work
when a more specific note does not already own the finding.

Rodman also expects Claw to make sure Claw-authored PRs actually get merged.
Merging to `main` is the handoff to the repository's Terragrunt/GitOps apply
path, so check and merge ownership is part of the operational work.

Claw-authored commits and PR titles should use Conventional Commit format, for
example `docs: update homelab runbook` or `fix: tighten openclaw network
policy`.

## Open Findings

- **Status:** open; local proxy workaround verified
- **Area:** Octelium / public gRPC transport
- **Evidence:** During the 2026-08-25 NOFX catalog rollout,
  `octelium-api.stinkyboi.com` returned Cloudflare HTTP 522 after the protected
  origin-rule workflow succeeded. The router refused the CronJob's hard-coded
  `10.1.0.1:49152` control endpoint, while the dedicated
  `10.1.0.200:30443` NodePort returned the expected unauthenticated
  `grpc-status: 16`. A TLS-preserving local CONNECT proxy to that NodePort
  allowed the signed PR `#719` catalog to apply and live verification to pass.
- **Risk:** Router control-port changes prevent `octelium-api-upnp` from
  renewing TCP/8443, leaving public CLI, VPN, and admin operations unavailable
  even while portal and app tunnel traffic remains healthy.
- **Next step:** Replace the hard-coded UPnP control URL in
  `clusters/homelab/apps/istio/octelium-api-upnp.yaml` with tested IGD
  discovery that still originates from `zimaboard-0`; verify the router lease,
  public `grpc-status: 16`, and an authenticated CLI call after rollout.

- **Status:** mitigated; hardware diagnosis pending
- **Area:** Acer control plane / storage integrity
- **Evidence:** On 2026-08-25, two OpenClaw image modules on `acer` contained
  bit-flipped source bytes. The API server also could not decode the
  `clustersecretstores.external-secrets.io` CRD or decrypt obsolete Argo CD
  Helm history revision `v6` and generated `media-postgres-arr-env`, preventing
  CRD and Secret informer sync. The dated
  `scripts/recover-kubernetes-storage-20260825.sh` recovery snapshots etcd,
  removes only those corrupt records, and reschedules OpenClaw away from
  `acer`; desired state keeps it excluded.
- **Risk:** Other image layers or etcd records may be damaged, and the single
  control-plane node remains a cluster-wide failure domain.
- **Next step:** renew authenticated Talos access, take an off-node etcd
  snapshot, then test or replace `acer` memory and system storage before
  allowing workloads to schedule there again.

- **Status:** mitigated; local database storage still required
- **Area:** Octelium / access recovery
- **Evidence:** On 2026-07-29, an NFS-backed `octelium-postgres` stall made the
  public login origin return HTTP 502 while repeated CLI retries accumulated
  15 disconnected `homelab-owner` client sessions alongside its browser
  session. Octelium then denied new authentication at the default 16-session
  ceiling even after PostgreSQL recovered. The service catalog now declares
  core `ClusterConfig` `default` with human `maxPerUser: 32`; the canonical
  runbook applies that kind separately before the normal catalog resources.
  During the confirmed live rollout on 2026-07-29, PostgreSQL again accepted
  sockets while bounded `SELECT 1` queries timed out and the console save
  remained pending. The storage manifest now uses `SELECT 1` for readiness and
  liveness instead of the shallow `pg_isready` check. The first recovery phase
  temporarily fences the StatefulSet at zero replicas without deleting its
  retained PVC; the follow-up restores one replica on the new revision. That
  fresh pod stalled again on `acer`, while earlier node-level NFS evidence
  showed millions of write timeouts there and almost none on the ZimaBoards.
  Desired state now pins only `octelium-postgres` to `zimaboard-1`. Live
  verification then caught the same retained NFS claim query-stalling again on
  `zimaboard-1`; the SQL liveness probe correctly marked the pod unready. The
  runtime liveness window is now 90 seconds so this failure restarts instead of
  leaving Octelium authentication unavailable for 30 minutes.
- **Risk:** The larger ceiling restores recovery headroom but does not make the
  QNAP NFS path reliable; another retry storm could still fill 32 sessions.
- **Next step:** Move PostgreSQL to reviewed local block storage; the cluster
  currently exposes only `nfs-default`, so that migration needs a declared
  Talos volume and Kubernetes storage path. Keep the availability alert active,
  delete disconnected sessions through `octeliumctl delete session`, and treat
  renewed probe failures as the storage incident rather than an Octelium
  routing failure.

- **Status:** resolved; public Octelium client connection verified
- **Area:** Octelium / public gRPC transport
- **Evidence:** After PostgreSQL recovered, authenticated Octelium CLI calls
  still hung through `octelium-api.stinkyboi.com` while the same client and
  session succeeded through a TLS-preserving local CONNECT proxy to the
  in-cluster Istio gateway. Both `cloudflared` `2026.6.1` replicas selected
  QUIC successfully but logged that `2026.7.3` was the recommended update.
  After that digest-pinned update rolled out healthy, authenticated public
  `octelium status` still hung. The direct route completed login and reached
  `isConnected: true` with the unprivileged `gvisor` implementation, proving
  the client, session, database, and Istio origin path. The first protected
  reconciliation run injected the scoped token successfully, but Cloudflare
  returned `Undefined zone setting: grpc`; its replacement
  `long_lived_grpc` is visible but non-editable and returns API error `1015`.
  Cloudflare's current documentation states that Tunnel public-hostname
  deployments do not support gRPC. The Xfinity gateway exposes a working UPnP
  IGD, and the dedicated NodePort on `10.1.0.200:30443` returned the expected
  unauthenticated gRPC status directly. The gateway rejected a mapping created
  from the operator workstation with UPnP error `402`, because its
  implementation requires the request to originate from the target LAN client.
  The host-networked reconciliation then succeeded from `zimaboard-0`, and the
  router lists TCP/443 to `10.1.0.200:30443` with its minimum 86,400-second
  lease. Direct origin probes still return `grpc-status: 16`, but Cloudflare
  receives HTTP `502` and direct WAN IPv4 connections time out. Xfinity
  documents that Advanced Security can block all inbound traffic to UPnP and
  port-forwarded devices, and its published blocked-port list does not include
  `8443`. Cloudflare Origin Rules can keep the client on standard TCP/443 while
  overriding only the origin destination port on every plan. The live
  TCP/8443 mapping changed the edge failure from a timeout to Cloudflare HTTP
  `525`, while the dedicated Envoy logged `filter_chain_not_found` for that
  connection. This proves the high port reaches Istio and that Cloudflare's
  origin handshake omits the SNI required by the original exact-host Gateway.
  After the SNI-tolerant Gateway and API-only `VirtualService` rolled out, the
  Cloudflare TCP/8443 probe returned HTTP/2 `200` with `grpc-status: 16`, while
  a request for another Host returned `route_not_found`. Protected run
  `30716050087` then exposed the final cause: the zone used Flexible SSL, so
  Cloudflare sent plaintext to the TLS-only origin and returned HTTP `520`.
  PR `#638` added a hostname-scoped Full (strict) Configuration Rule alongside
  the existing destination-port rule. Protected run `30716932077` created and
  verified both rules. The standard TCP/443 API probe then returned HTTP/2
  `200`, `content-type: application/grpc`, and the expected unauthenticated
  `grpc-status: 16`. A real Octelium `v0.35.0` client authenticated as
  `homelab-owner`, printed `Connected successfully`, and reported
  `isConnected: true`; the test session then shut down cleanly.
- **Risk:** Public client availability still depends on the leased UPnP mapping,
  the two exact-host Cloudflare rules, and normal certificate renewal.
- **Next step:** Keep the protected reconciliation workflow rerunnable and
  treat a missing standard-port `grpc-status: 16` response as edge-path drift
  before investigating Octelium authentication or storage.

- **Status:** open; alert semantics fixed, scrape failure unresolved
- **Area:** observability / kube-state-metrics
- **Evidence:** Read-only checks on 2026-07-19 showed all four expected nodes
  `Ready`, and the kube-state-metrics endpoint exported `kube_node_info` for
  each node. Prometheus nevertheless reported the target as `up == 0`, spent
  10.000 seconds on each scrape, and ingested zero samples. Both the minimum
  and maximum target state were zero across the full 15-day retention window.
  The previous Grafana inventory query used `or vector(0)`, converting this
  telemetry outage into a false report that all four machines were missing.
- **Risk:** kube-state-metrics-backed inventory, readiness, and pressure rules
  cannot observe Kubernetes node state while the scrape is unavailable. A
  telemetry failure can conceal a real node problem if it is not alerted
  separately.
- **Next step:** The Grafana rules now alert directly on kube-state-metrics
  availability and only evaluate expected hardware inventory while that scrape
  is healthy. Separately measure the Prometheus-to-exporter path and determine
  whether the 10-second deadline, exporter payload, or ambient-mesh transport
  prevents the scrape from completing before changing the scrape configuration.

- **Status:** fixed
- **Area:** networking / DNS
- **Evidence:** Read-only checks on 2026-07-19 showed that the configured
  Cloudflare Family resolvers (`1.1.1.3` and `1.0.0.3`) returned `0.0.0.0` and
  `::` for a required Prowlarr indexer while standard Cloudflare DNS returned
  its public IPv4 addresses. Prowlarr general HTTPS egress remained healthy,
  proving the connection refusal came from DNS sinkholing rather than TLS,
  IPv6, or workload egress. `platform-dns` now uses `1.1.1.1` and `1.0.0.1`.
- **Risk:** cluster DNS no longer receives Cloudflare Family malware and adult
  category filtering. Silent category sinkholes are incompatible with required
  media indexers and can present as application transport failures.
- **Next step:** keep explicit public resolvers and monitor CoreDNS errors. If
  category filtering is required later, introduce a reviewed allow/deny policy
  with observable denial behavior instead of switching the shared resolver back
  to an opaque sinkhole response.

- **Status:** `affine-postgres` restored; `media-postgres` and Prowlarr
  cutovers validated; `n8n-postgres` restore prepared; Radarr
  local-config cutover prepared and live validation pending; open for other NFS
  workloads
- **Area:** storage / database recovery
- **Evidence:** Read-only inspection on 2026-07-19 found simultaneous probe
  failures across NFS-backed workloads on multiple healthy Kubernetes nodes.
  `media-postgres` remained in crash recovery longer than its liveness window,
  so kubelet repeatedly terminated it with exit code 137 before it could become
  ready. Prowlarr then returned PostgreSQL connection-refused errors while Argo
  CD still reported the app healthy. The QNAP NFS exports and RPC services were
  reachable when checked after the initial stall. The repository now gives
  `media-postgres` a 30-minute startup window and a 120-second termination grace
  period. A recurrence on 2026-07-20 affected NFS-backed workloads across three
  nodes. `media-postgres`, `n8n-postgres`, and `octelium-postgres` recovered
  after kubelet restarts, but `affine-postgres` entered more than 130 restarts
  and then failed to open `postmaster.pid` with `Permission denied`. AFFiNE's
  first recovery phase set the StatefulSet to zero replicas without modifying
  its PVC; Argo CD then reported the Application synced and healthy, the pod was
  absent, and the retained claim remained bound. The second phase uses a
  repository-owned, early-wave Sync hook to remove only the fenced stale lock
  before restoring one replica. Argo recreates a failed hook before retrying. A
  completion marker on the declared PostgreSQL claim makes later runs read-only
  after the first successful recovery, and a fresh claim safely skips removal.
  The restore configuration tolerates 30 minutes of startup or liveness
  failures and grants 120 seconds for shutdown. Live rollout validation at
  `d7268376` captured the hook removing the stale lock and writing its marker;
  PostgreSQL then completed crash recovery, became ready with zero restarts,
  retained pgvector `0.8.1` and the committed settings, and returned AFFiNE to a
  synced, healthy Argo CD state. HTTPS, native-client CORS, server discovery,
  and the anonymous-workspace denial checks all passed. The incident-only hook
  was removed from steady-state desired state after those checks. Read-only
  inspection on 2026-07-24 confirmed another broad recurrence:
  `media-postgres` had restarted 148 times in four days, Deluge's app and
  Gluetun containers had restarted 669 and 413 times in ten days, and Radarr
  had restarted 147 times in three and a half days. Sonarr and Prowlarr had
  zero restarts in their current pods but logged repeated PostgreSQL connection
  refusals and read timeouts. Prometheus recorded about 22,465 I/O-wait
  task-seconds for `media-postgres`, 11,062 for Radarr, 5,677 for Deluge, 5,141
  for Sonarr, and 2,476 for Prowlarr over the preceding 24 hours, with no media
  container OOM events. The NFSv3 client statistics shared by the affected
  mounts on `acer` recorded 7,732,718 WRITE RPC timeouts and roughly 69 seconds
  of average write execution time over the mount lifetime, compared with 12
  and 24 WRITE timeouts and roughly 46 and 87 milliseconds average execution
  time on `zimaboard-0` and `zimaboard-1`. Deluge's VPN metric was healthy
  99.8% of the last 24 hours while daemon RPC health was only 65.3%; its
  previous app instance stalled during `/config` ownership initialization
  before the liveness probe restarted it. All affected persistent volumes
  target the QNAP at `10.1.0.2` over NFSv3.
  A new recurrence on 2026-07-29 provided a 20-second kernel mount-stat delta:
  311 `media-postgres` NFS writes completed with about 26.9 seconds average
  queue time, 8.1 seconds RPC round-trip, and 35.0 seconds execution per write.
  PostgreSQL readiness failed immediately before Prowlarr timed out and then
  received connection refusals. Concurrent probe failures affected NFS-backed
  workloads on `acer`, `zimaboard-0`, and `zimaboard-1`, while every node
  remained Ready and physical NIC error counters stayed at zero. Desired state
  now stages `media-postgres` on an `acer`-pinned local volume, uses real SQL
  for readiness, disables TCP during the verified cutover backup, and then
  replaces the legacy StatefulSet with a writable local-only instance. A
  one-time PID/socket fence prevents writer overlap. Nightly verified logical
  backups retain 14 days on NFS without storing role password hashes, and the
  repository recovery overlay fences the writer and schedule before restore.
  Live phase-one validation at signed revision `24da3a01` confirmed Argo CD
  synced and healthy, the retained local pod Ready on `acer`, the migration
  marker and all six application databases present, read-only mode enabled,
  TCP disabled, and 50 `SELECT 1` probes completing in 1.63 seconds. Backup
  `20260730T045748Z` verified the six custom-format dumps and password-free
  globals before phase two was released.
  Live phase-two validation at signed revision `88098e7f` confirmed the legacy
  writer at zero replicas, the local-only writer Ready on `acer`, the one-time
  fence present, read/write SQL available, and 50 probes completing in 1.71
  seconds. The remaining Prowlarr search stall was outside PostgreSQL: its raw
  tracker HTTPS request completed in 0.49 seconds, while one read of the
  NFS-backed `/config/config.xml` took 10.2 seconds and two live searches
  exceeded 30 seconds. The equivalent reads in Sonarr and Radarr on
  `zimaboard-0` took 79 and 281 milliseconds, and that node's NFS client
  recorded 12 lifetime write timeouts versus 26,065,641 on `acer`. Desired
  state now pins Prowlarr to `zimaboard-0` without replacing its retained PVC.
  Final read-only validation on 2026-07-30 found both Argo CD Applications
  synced and healthy. Prowlarr was Ready with zero restarts on `zimaboard-0`
  using its original retained claim; 20 config reads had a 17.34-millisecond
  median and 30.66-millisecond p95. Prowlarr, Sonarr, and Radarr searches each
  returned 50 results in 2.916, 3.519, and 3.714 seconds, respectively, with no
  indexer or PostgreSQL timeout/refusal errors after the Prowlarr rollout. The
  local PostgreSQL writer remained Ready with zero restarts, the legacy writer
  remained at zero replicas, a rolled-back temporary write passed, and 50
  queries completed in 1.669 seconds. The first scheduled backup Job completed
  at 03:00 Pacific with no failures. Backup `20260730T100002Z` verified
  password-free globals and all six dumps; the successful Job also exercised
  the live 14-day retention command without error.
  Read-only inspection on 2026-08-01 found Radarr independently
  `CrashLoopBackOff` with 785 restarts because its NFS-backed
  `/config/config.xml` was empty. The local-config Deluge replacement remained
  healthy with zero restarts, 17 torrents, and successful Sonarr connectivity,
  separating this recurrence from the completed Deluge cutover.
  On 2026-08-03, `n8n-postgres` entered `CrashLoopBackOff` and failed to open
  its NFS-backed `postmaster.pid` with `Permission denied`; n8n then failed
  database initialization and its public callback returned HTTP 503 `no healthy
  upstream`. Argo CD remained synced, ExternalSecrets remained ready, and the
  Kubernetes nodes and QNAP RPC services were reachable. Read-only node-side
  inspection found no PostgreSQL process or other PVC consumer; `pgdata` was
  mode `0700` with UID/GID `65534`, while `postmaster.pid` was a zero-byte mode
  `000` file with the same owner. Phase one fenced the StatefulSet at zero
  replicas without modifying its retained claim, while adding 30-minute startup
  and liveness windows plus 120 seconds for shutdown. Live validation at
  `e9f42313` confirmed Argo CD synced and healthy, desired/current replicas
  `0/0`, the old pod, process, and cgroup absent, no other claim consumer, and
  the original PVC still bound to the same volume. Phase two declares that
  claim at sync wave `-2`, runs the completion-marked recovery hook at wave
  `-1`, and restores one replica at wave `0`.
  Read-only inspection on 2026-08-03 reconfirmed the zero-byte file and found
  four valid built-in backup archives; the newest, dated 2026-07-27, contains a
  complete config with one API key plus the expected PostgreSQL and auth tags.
  The 81 MiB config tree is small relative to the 13.89 GB available on
  `zimaboard-0`. Desired state now declares a guarded recovery into retained
  local storage, preserves the invalid file and NFS claim, and schedules
  verified 14-day archives back to NFS. Live recovery remains unverified.
- **Risk:** probe hardening limits crash-recovery loops but cannot make the
  shared storage path responsive. Sonarr and Prowlarr can remain Kubernetes
  `Running` while database calls fail, while Deluge and Radarr turn sustained
  I/O stalls into restart loops. The same failure domain affects unrelated
  NFS-backed workloads across the cluster. The nominal local-disk RPO is 24
  hours, but the actual RPO is the age of the newest verified set and can be
  older. A failed nightly NFS backup has no freshness alert while the
  kube-state-metrics scrape path is unhealthy. n8n remains unavailable until
  the recovery hook succeeds and the database and application checks pass.
- **Next step:** merge and live-validate the n8n PostgreSQL restore, then remove
  its one-shot recovery hook from desired state while retaining the explicit
  claim and hardened probes.
  Sync and observe the Radarr recovery revision, verify the migration marker,
  API identity, integrations, and first scheduled archive, then remove the
  migration-only NFS mount in a follow-up revision. Inspect QNAP pool, disk,
  NFS-service, and network history because the same failure domain still
  affects other NFS-backed workloads. Check scheduled backups manually after
  storage incidents, and restore backup freshness alerting when a reliable
  metric source is available.

- **Status:** PostgreSQL alert path mitigated; kube-state-metrics scrape open
- **Area:** monitoring / PostgreSQL availability
- **Evidence:** Read-only validation on 2026-07-20 found Prometheus reporting
  `up{job="kube-state-metrics"} == 0` with a scrape `context deadline exceeded`,
  even though the kube-state-metrics pod and EndpointSlice were ready and a
  local port-forward returned metrics. Ztunnel recorded inbound HBONE
  connections from the correctly identified Prometheus service account to the
  kube-state-metrics pod timing out with zero bytes transferred. The new
  `homelab-postgres-unavailable` Grafana rule therefore uses kubelet
  `prober_probe_total` readiness counters, which live Prometheus queries
  confirmed for `affine-postgres-0`, `media-postgres-0`, `n8n-postgres-0`, and
  `octelium-postgres-0`. The healthy expression returned no series, while a
  simulated missing pod returned a labeled alert instance. The writable
  cutover revision changes the media target to `media-postgres-local-0`; that
  series still requires live rollout validation.
- **Risk:** Existing Grafana node, pod, Deployment, and PVC rules that depend on
  kube-state-metrics can remain in `NoData/OK` until that scrape path is
  restored. The generic Prometheus-target-down rule reports the failed target,
  but it does not replace the missing workload telemetry.
- **Next step:** diagnose and fix the cross-node ambient HBONE path through a
  repository-owned Istio or workload rollout change, then verify
  `up{job="kube-state-metrics"} == 1` and that the kube-state-metrics-backed
  Grafana rules return live series.

- **Status:** mitigated; 30-minute rollout validation passed
- **Area:** AFFiNE / storage I/O
- **Evidence:** The operator reported that QNAP responsiveness returned several
  minutes after AFFiNE, its PostgreSQL database, and Redis were scaled to zero.
  The previous Redis desired state added two persistence paths that AFFiNE's
  official deployment does not use: AOF with an NFS `fsync` every second and an
  RDB snapshot after 1,000 changes in 60 seconds. AOF rewrites and RDB snapshots
  can rewrite the full Redis dataset. The deployed mitigation now uses a
  node-local `emptyDir` for Redis, retains the former NFS claim read-only, and
  paces/compresses PostgreSQL checkpoint and WAL writes. During the 2026-07-16
  rollout, AFFiNE stayed synced, healthy, and restart-free for more than 30
  minutes. Redis reported AOF and RDB persistence disabled. The `acer` NFS
  client averaged about 4.2 RPC/s, 0.49 writes/s, and 0.27 commits/s with no
  retransmissions; wired QNAP latency remained sub-millisecond with no packet
  loss.
- **Risk:** Redis is now ephemeral, so a pod or node restart can discard cache
  entries and queued work. PostgreSQL remains durable on the QNAP and still
  needs normal backup and latency monitoring.
- **Next step:** keep the mitigation. Retain the former Redis claim until the
  rollback window closes, then remove it through the normal GitOps workflow.
  Track remaining operator-to-wired latency under the separate networking
  finding below.

- **Status:** open
- **Area:** networking / storage access
- **Evidence:** Read-only checks on 2026-07-13 isolated the remaining NAS
  slowness to the router/AP-to-wired-switch path. From the operator Mac,
  `10.1.0.1` averaged about 4 ms while the QNAP and every wired Talos node
  averaged roughly 600-1,100 ms. From `zimaboard-0`, the QNAP averaged 0.85 ms
  and `zimaboard-1` averaged 0.62 ms, but the router averaged 271 ms. A 64 MiB
  memory-only TCP transfer from the Wi-Fi operator Mac to a wired Talos node
  took 70.4 seconds (about 7.6 Mbit/s), while a wired pod read an existing QNAP
  file at 108 MB/s. Talos node NIC counters showed 1 Gbit/full-duplex links
  without meaningful errors, and cluster NFS traffic was nearly idle after
  OpenClaw stopped. AFFiNE,
  AFFiNE PostgreSQL, and AFFiNE Redis were temporarily scaled to zero by an
  explicit operator-requested `kubectl scale`; OpenClaw was also held at zero,
  but the cross-uplink latency initially remained. The operator later reported
  that QNAP responsiveness returned after AFFiNE had been off for several
  minutes. That timing correlates the recovery with AFFiNE shutdown, but the
  fast wired NFS benchmark and slow router boundary still leave the original
  gateway-path symptom unexplained. The 2026-07-16 AFFiNE rollout reproduced
  mild cross-uplink jitter while NFS remained nearly idle: the Mac saw the QNAP
  and `acer` rise together to roughly 40 ms while the router stayed near 4 ms,
  but `acer` continued reaching the QNAP in about 0.2-0.3 ms. This isolates the
  remaining symptom from AFFiNE's Redis and PostgreSQL storage activity. On
  2026-07-18 the Mac measured 30-60% packet loss to every wired Talos node and
  the QNAP while the router remained at 0% loss. During the same incident,
  public sites returned Cloudflare 524 errors and `cloudflared` repeatedly
  failed QUIC handshakes with `no recent network activity`. The GitOps
  mitigation now uses cloudflared automatic transport selection and permits
  TCP/7844 so public HTTP traffic can fall back to HTTP/2. The emergency
  rollout also exposed a circular recovery dependency: the local Kubernetes
  API had 70-80% packet loss, the homelab GitHub Actions runner was offline,
  and policy-bot could not approve the PR. A bounded GitHub-hosted recovery
  attempt could not publish `kubernetes-api.ci` because authenticated Octelium
  gRPC calls through Cloudflare lost their trailers, so no Argo CD operation
  was submitted. A later 2026-07-18 sample deteriorated to 100% loss from the
  Mac to `acer`, while the Xfinity gateway remained at 0% loss; the QNAP and
  worker nodes still lost 60-80% of packets. The Mac's `en0` counters showed
  no errors or collisions during the same interval, further isolating the
  fault to the gateway-to-wired-segment path rather than the operator host.
- **Risk:** traffic that crosses between the router/Wi-Fi side and the wired
  homelab appears to hang even when the NAS and wired switch fabric are healthy.
  Operator SMB access can still be slow, and the same failure can block both
  the normal PR approval path and remote GitOps recovery. OpenClaw was restored
  on 2026-07-19; its separate read-storm risk remains tracked below.
- **Next step:** inspect the router/AP-to-switch uplink negotiation, utilization,
  error/drop counters, spanning-tree state, patch cable, and switch ports.
  Restore reliable UDP/7844 so long-lived Octelium gRPC streams remain on QUIC;
  HTTP/2 fallback preserves basic public access but is not the preferred steady
  state. Design and validate a least-privilege, repository-owned recovery path
  that does not depend on policy-bot, the in-cluster runner, or the public
  Octelium control path being healthy.
  Restore OpenClaw separately so its known read storm cannot overlap the AFFiNE
  test.

- **Status:** open
- **Area:** agent runtime / storage
- **Evidence:** Before OpenClaw was stopped on 2026-07-13, `acer` sustained about
  3,850 NFSv3 reads per second and 206 Mbit/s of receive traffic. Process-level
  counters attributed roughly 33 MiB/s of physical reads to
  `openclaw-gateway`; AFFiNE, PostgreSQL, Deluge, and other sampled NFS-mounted
  containers were nearly idle. OpenClaw's read-only `memory status` command
  timed out while this activity continued. After OpenClaw was restored on
  2026-07-19, its gateway stopped accepting loopback connections for 22 seconds:
  Kubernetes recorded six readiness timeouts from 17:33:01-17:33:23 UTC, then
  OpenClaw's health monitor released a stale `Memory Dreaming Promotion` session
  and the gateway recovered at 17:33:27 UTC. A 2026-07-26 read-only inspection
  found the app had 584 restarts in seven days because exec probes were failing
  with `OCI runtime exec failed` / `setns` errors even while logs showed normal
  gateway startup. The app and proxy now use native HTTP probes through the
  proxy so kubelet no longer depends on container exec, while probe success
  still requires the loopback gateway to return an HTTP response. A TCP probe
  of the proxy listener was rejected because it could succeed before the proxy
  discovered that the upstream gateway was unavailable.
- **Risk:** hot OpenClaw gateway state, memory indexing, or workspace scanning
  on the QNAP-backed PVC can amplify storage pressure and obscure independent
  network faults.
- **Next step:** after fixing the router/switch uplink, reproduce the OpenClaw
  load in a controlled window and identify which gateway state path is being
  scanned. Keep durable agent state on the PVC, but move any rebuildable hot
  index, cache, or watcher-heavy state to pod-local storage through reviewed
  GitOps desired state if the read storm returns. Correlate any future liveness
  restart with the gateway log, NFS counters, and the active memory job before
  changing storage behavior.

- **Status:** fixed in desired state; rollout pending
- **Area:** agent runtime / Codex diagnostics
- **Evidence:** On 2026-08-13, a minimal Codex turn reproduced the gateway
  stall after the sandbox error was fixed. The per-agent `codex-home` was 8.7
  GiB on NFS: `logs_2.sqlite` was 5.7 GB and its WAL was 2.2 GB. During a fresh
  turn, Codex read 2.2 GB in 22 seconds while cgroup memory climbed from 1.1 to
  1.6 GB; gateway probes then timed out and liveness restarted the app.
  Moving only SQLite exposed a second startup backfill over 5,651 native Codex
  sessions. Repository desired state now mounts the whole per-agent Codex home
  from a `2Gi` pod-local `emptyDir` while leaving durable OpenClaw state on the
  PVC. On 2026-08-22, the shared Nix store alone measured `2.7Gi`; the old
  `3Gi` app limit then evicted the pod while its replacement reproduced the
  same base footprint. Desired state now requests `5Gi` and limits `6Gi`,
  reserving the separately capped `2Gi` Codex runtime while retaining headroom
  for writable-layer and log overhead.
- **Risk:** Codex-native threads, indexes, caches, and diagnostics reset with a
  pod replacement. OpenClaw retains its own session history and OAuth profile.
- **Validation:** PR #672 rolled out at commit `d858083b`. The pod-local Codex
  home was 109 MiB, a minimal turn returned `OPENCLAW_OK` in 7.3 seconds, and
  the ready pod retained zero restarts. After the storage-envelope change
  rolls out, verify the replacement pod requests `5Gi`, limits `6Gi`, and
  remains ready without another `Evicted` replacement.

- **Status:** fixed
- **Area:** agent runtime / startup
- **Evidence:** The first 2026-08-13 rollout stalled in `bootstrap-config`
  before the app container started. Automatic `openclaw doctor --fix` found
  5,344 orphan transcripts and remained blocked scanning the NFS-backed session
  directory. Repository bootstrap now validates config without running doctor.
- **Risk:** future OpenClaw upgrades that require config migration will fail
  validation instead of repairing persisted state automatically.
- **Validation:** the replacement pod completed both init containers and became
  ready. Run doctor or a specific migration only as reviewed maintenance when
  an upgrade requires it.

- **Status:** fixed
- **Area:** agent runtime / sandboxing
- **Evidence:** On 2026-07-19, restored OpenClaw cron runs reported that
  `agents.defaults.sandbox.mode=non-main` requires Docker, but the workload has
  no Docker command or sandbox backend. The affected nested cron lanes failed
  rather than falling back to the embedded backend. On 2026-08-13, a direct
  agent request failed with the same error while the gateway, OAuth profile,
  secrets, pod, and public route were healthy. Repository desired state now
  sets the sandbox mode to `off` because the workload has no supported backend.
- **Risk:** agent execution is contained by the Kubernetes workload, not an
  OpenClaw sandbox. Non-main and scheduled work can access resources available
  inside the pod, including the persistent workspace, operator toolbox, and
  mounted application credentials. The service account token is disabled and
  ingress is restricted, but workload egress is not restricted.
- **Validation:** live config reported sandbox mode `off`, and a direct agent
  request completed. Add and validate a supported backend before enabling
  OpenClaw sandboxing again.

- **Status:** open
- **Area:** CI/CD identity
- **Evidence:** a read-only IAM inspection on 2026-07-13 found that the live
  `Github-TF-State` trust policy accepts `repo:Stuhlmuller/homelab:*` and
  `repo:Stuhlmuller/github-iac:*`, while `docs/ci-cd.md` documents only the
  `homelab-plan` and `homelab-production` environment subjects.
- **Risk:** the live GitHub OIDC trust boundary is broader than this
  repository's documented production and plan environments; narrowing it
  without inspecting `github-iac` could also break an active external consumer.
- **Next step:** inventory every workflow that assumes the role, decide whether
  `github-iac` needs a separate role, then manage and validate the trust policy
  through a reviewed operator-owned Terragrunt unit before removing wildcard
  subjects.

- **Status:** open
- **Area:** agent runtime
- **Evidence:** OpenClaw pod currently runs on an NFS-backed PVC where files can
  appear as `nobody:nogroup`; PR #296 configures workspace scratch paths and
  Git safe-directory state in pod bootstrap.
- **Risk:** future agent work can hit Git ownership checks or brittle cleanup
  paths if runtime setup drifts from the PVC ownership model.
- **Next step:** after PR #296 syncs, verify the rolled pod has
  `GIT_CONFIG_GLOBAL=/data/openclaw/gitconfig`, can run `git status` in
  `/data/openclaw/workspace`, and has
  `/data/openclaw/workspace/.openclaw/trash`.
- **Status:** fixed
- **Area:** agent runtime
- **Evidence:** Rodman requires Claw to sign all commits. The current OpenClaw
  image lacks `gpg` and `ssh-keygen`; PR #297 configured pod bootstrap to
  provide a persistent SSH signing helper and key.
- **Risk:** unsigned commits weaken auditability for agent-authored
  infrastructure changes.
- **Next step:** after PR #297 syncs, verify the rolled pod has
  `commit.gpgsign=true` and that future Claw branch commits show a good SSH
  signature before push.
- **Status:** open
- **Area:** CI/CD
- **Evidence:** the repository currently accepts squash merges only. GitHub
  creates the final squash commit on `main`, while Claw's branch commits are
  locally SSH-signed before push.
- **Risk:** GitHub's squash commit may not carry Claw's local SSH signature,
  which can blur the "all Claw commits are signed" rule unless the repository
  policy or merge workflow explicitly accounts for it.
- **Next step:** decide whether to keep squash-only merges with GitHub-signed
  mainline commits, allow rebase/merge methods that preserve Claw-signed branch
  commits, or add a bot-supported path for signed squash commits.

- **Status:** fixed
- **Area:** CI/CD
- **Evidence:** PR #374 updates `scripts/ci/terragrunt-plan.sh`,
  `scripts/ci/terragrunt-apply.sh`, and
  `scripts/ci/terragrunt-filter-base.sh` after PR #371 exposed that
  current-tree `terragrunt run --all --filter-affected` cannot enter a deleted
  unit directory.
- **Risk:** deleting a Terragrunt unit can otherwise leave remote-state-backed
  cloud or Kubernetes resources orphaned while reviewers assume post-merge apply
  cleaned them up.
- **Next step:** keep deleted-unit cleanup in the CI path: generate a temporary
  empty Terragrunt unit at each deleted path, rely on `IaC/root.hcl` to target
  the original backend key, list the remote-state resources, and apply the saved
  destroy plan before applying the current checkout.
- **Status:** fixed
- **Area:** CI/CD
- **Evidence:** `.github/workflows/terragrunt-apply.yml` now resolves the latest
  successful workflow `head_sha` and validates it as an ancestor before setting
  the Terragrunt affected-unit base. `scripts/ci/secret-scan.sh` scopes manual
  dispatch history scanning to `HEAD^..HEAD`.
- **Risk:** using only the immediately preceding push could let a failed apply's
  units fall out of every later affected set; scanning all reachable history on
  manual dispatch also re-raised unrelated historical findings.
- **Next step:** keep `actions: read` on the apply job. If no trustworthy
  successful base exists, apply all current unit groups and retain the explicit
  warning that deleted-unit retirement cannot be inferred.
- **Status:** open
- **Area:** secrets / CI/CD
- **Evidence:** June 2026 security audit found
  `IaC/live/kubernetes-secrets/external-secrets-aws-ssm-auth/terragrunt.hcl`
  still sources `../../../modules/kubernetes-secret-from-ssm`, whose module
  reads decrypted SSM values into a Kubernetes Secret resource and OpenTofu
  state.
- **Risk:** decrypted External Secrets AWS provider credentials could otherwise
  be exposed to anyone or anything with access to OpenTofu state, plan caches, or
  CI artifacts.
- **Next step:** keep this finding open until repo-owned remediation replaces
  the state-writing stack, removes any older state object that contained the
  Kubernetes Secret data, and rotates the External Secrets IAM access key.
- **Status:** open
- **Area:** platform service / GitOps
- **Evidence:** June 2026 security audit found remaining structural hardening
  work: the shared Argo CD AppProject can still deploy cluster-scoped RBAC,
  Kiali remains anonymous/view-only on the tailnet, several app-template
  workloads need explicit restricted container security contexts.
- **Risk:** these are reviewability, reconnaissance, and lateral-movement risks
  that are larger than a single safe patch.
- **Next step:** split AppProjects, add Kiali identity controls, harden
  compatible app-template values, and keep shared platform changes small enough
  to validate independently.
- **Status:** fixed
- **Area:** infrastructure supply chain
- **Evidence:** The Terragrunt catalog release tag `0.4.0` was verified with
  `git ls-remote` as commit `19df2cb291eef0084cafb85bed644dcdb082108c`, and
  the bootstrap/Entra units now pin module sources to that immutable commit.
- **Risk:** mutable or retargeted module tags can change infrastructure module
  code outside this repository's review path.
- **Next step:** keep remote Terragrunt module sources pinned to immutable
  commits, or vendor the module before using a mutable release tag again.
- **Status:** fixed
- **Area:** platform service / Pod Security
- **Evidence:** June 2026 security audits found namespaces using weak
  `audit`/`warn` Pod Security labels. The fixes keep required
  `enforce: privileged` exceptions for Deluge VPN, Istio ingress, Octelium,
  Octelium client, Tailscale, and the host-networked GitHub Actions runner,
  keep baseline enforcement for `finance`, and require repo-owned namespaces to
  set `audit` and `warn` to `restricted` through Conftest.
- **Risk:** privileged audit/warn labels hide workloads that could run under a
  tighter profile or accidentally expand the exception blast radius.
- **Next step:** continue splitting the Deluge VPN privilege exception into a
  dedicated namespace once the media workloads can stay restricted.
- **Status:** open
- **Area:** workload reliability / Deluge
- **Evidence:** On 2026-06-15 UTC, Deluge was Kubernetes-ready and Argo CD
  `Synced/Healthy`, but `deluged` was repeatedly crashing with
  `libtorrent::libtorrent_exception: invalid type requested from entry`.
  `deluge_daemon_rpc_healthy` was `0` until the documented
  `session.state` recovery restored `/config/session.state.bak` and archived
  the broken state file as `session.state.broken-20260615T040836Z`. On
  2026-07-24, Deluge reported zero loaded torrents even though
  `/config/state` still contained 14 `.torrent` files and a 37,454-byte
  `torrents.fastresume`. Both the live `torrents.state` and its backup were
  only 80 bytes. The two retained `torrent-recovery-20260720` archives
  preserved all 14 metadata files but their 2,287-byte catalogs each referenced
  only one torrent, so neither was a complete rollback source. The daemon
  logged `Bad shutdown detected` followed by `Finished loading 0 torrents`.
  The startup wrapper validated `/config/session.state`, which holds libtorrent
  session settings, but did not validate or restore
  `/config/state/torrents.state`, which is the actual Deluge torrent catalog.
  During recovery validation, the still-running daemon rewrote the live catalog
  and fast-resume file to one entry, but nine retained `state-*.tar.xz`
  snapshots still held all 14 fast-resume records. After the guarded recovery
  rollout, a short NFS/RPC stall caused three 12-second liveness failures and
  Kubernetes killed the otherwise recoverable app container with exit code
  137. The restart then traversed the entire root-squashed `/config` tree in
  LinuxServer's recursive ownership hook, producing hundreds of rejected
  `chown` calls before Deluge reloaded all 14 torrents and resumed downloads.
  The recovered snapshot marked only three entries complete; 11 pointed at
  `/downloads/incomplete`, including nine shown as queued, even though all 11
  had complete-root files matching every expected file count and byte size.
- **Risk:** Deluge can be unavailable while Kubernetes readiness, Gluetun, and
  Argo CD still look healthy, and the same persisted-state corruption may
  recur after future pod or daemon restarts. Repeated bad-shutdown archives now
  preserve the empty catalog and can age out the last known-good recovery
  copies even though the individual torrent metadata files remain.
- **Next step:** guarded startup recovery now treats an empty
  `torrents.state` as invalid when `.torrent` files exist. It requires matching
  fast-resume records from the live file or a retained archive plus
  `/downloads`-scoped save paths before atomically restoring fast-resume data
  and rebuilding the catalog, and it archives the pre-recovery files. Runtime
  liveness now allows the same 30-minute recovery window as startup, and the
  wrapper skips the futile recursive ownership hook. Deluge reloaded all 14
  torrents and resumed downloads after the observed restart. The guarded
  operator reconciliation adopts exact-size complete-root files without
  replacement and makes libtorrent hash-check them before trusting completion.
  Its guard resumes verified entries and pauses hash failures instead of
  redownloading them. The active config volume now uses retained local storage
  on `zimaboard-0`; the initial guarded cold copy took 4 minutes 6 seconds for
  roughly 5.2 MB and retained the NFS claim for nightly archives. The
  replacement loaded all 17 torrents with no error-state entries or container
  restarts.
  This removes the recurring QNAP config stall from the daemon, probe, and
  catalog paths while keeping shared media on the NAS. Steady-state startup
  replaces LinuxServer's broad ownership hook with a non-recursive ownership
  assignment on the local config root, preserving clean bootstrap while
  avoiding a repeated scan and the futile root-squashed downloads `chown`. The
  first scheduled NFS archive,
  `20260731T103003Z.tar.gz`, completed and passed archive listing validation
  before the migration-only mount was removed from the app pod.
  On 2026-08-02, Gluetun then accumulated 11 clean Kubernetes-initiated
  restarts while its internal health loop could not pass traffic through
  `198.54.129.62`. The source AirVPN hostname had changed to
  `198.54.129.125`, but the completed `config-wireguard` init container had
  resolved it only once when the pod started. The resolver now runs in
  Gluetun's startup wrapper, so every sidecar restart rebuilds the normalized
  profile with the current DNS answer. Unused public-IP discovery is disabled
  to stop permission errors while clearing `/tmp/gluetun/ip`.
  Live rollout validation at merged revision `ea35c590` resolved the profile to
  `198.44.133.70`, returned Argo CD to `Synced/Healthy`, and left replacement
  pod `deluge-76c8959f9d-sx289` Ready with zero restarts after more than two
  minutes. VPN and daemon health were both `1`, all 17 torrents loaded with
  zero errors, and the pod mounted only `deluge-config-local` and
  `media-downloads`. The 2026-08-02 scheduled backup also completed and
  validated archive `20260802T103004Z.tar.gz`.
  Roughly three hours later, another VPN health failure exposed a restart
  bootstrap loop: Gluetun had changed the pod resolver to its own
  `127.0.0.1`, then Kubernetes restarted the container and the wrapper tried to
  resolve AirVPN before that local DNS server existed. Gluetun exited with
  `failed to resolve WireGuard endpoint hostname`, accumulated nine restarts,
  and left Argo CD `Progressing`. The wrapper now passes only the profile's
  client keys and IPv4 address to Gluetun's native AirVPN provider. Gluetun
  owns server selection, so container recovery no longer needs pre-start DNS
  or the removed writable normalized-profile volume.
  The first native-provider rollout at revision `a8093bf3` exposed one parser
  defect: splitting the profile on every `=` removed the WireGuard key's
  base64 padding. Revision `be8977d0` instead keeps everything after the first
  delimiter. After Argo CD exhausted the failed revision's bounded retries, it
  applied the correction without a manual refresh. Replacement pod
  `deluge-54dcf44bbd-hstck` reached Ready with zero restarts, Argo CD returned
  to `Synced/Healthy`, VPN and daemon health were both `1`, and all 17 torrents
  loaded with zero errors. Its only PVCs are `deluge-config-local` and
  `media-downloads`; the old NFS config claim and generated VPN-profile volume
  are absent.
