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

- **Status:** `affine-postgres` restored, partially mitigated for
  `media-postgres`, and open for the other PostgreSQL workloads
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
- **Risk:** probe hardening limits crash-recovery loops but cannot make the
  shared storage path responsive. Sonarr and Prowlarr can remain Kubernetes
  `Running` while database calls fail, while Deluge and Radarr turn sustained
  I/O stalls into restart loops. The same failure domain affects unrelated
  NFS-backed workloads across the cluster.
- **Next step:** the media PostgreSQL liveness window now matches its
  30-minute startup recovery window, which prevents brief NFS outages from
  immediately starting another crash-recovery cycle. Treat the QNAP and
  especially the `acer` NFS client path as the primary incident. Inspect QNAP
  pool, disk, NFS-service, and network history for the 2026-07-23/24 window;
  collect Talos kernel NFS diagnostics with a populated Talos client config;
  and benchmark NFS latency from each wired node. Evaluate moving PostgreSQL
  and other high-churn state to storage designed for database synchronous I/O.

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
  simulated missing pod returned a labeled alert instance.
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
  and the gateway recovered at 17:33:27 UTC. The app now has an HTTP readiness
  probe and a liveness probe that restarts the app container if a gateway stall
  persists, while the existing proxy readiness probe continues to withdraw the
  endpoint promptly.
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

- **Status:** open
- **Area:** agent runtime / sandboxing
- **Evidence:** On 2026-07-19, restored OpenClaw cron runs reported that
  `agents.defaults.sandbox.mode=non-main` requires Docker, but the workload has
  no Docker command or sandbox backend. The affected nested cron lanes failed
  rather than falling back to the embedded backend.
- **Risk:** non-main and scheduled agent work can fail even while the gateway
  and Control UI remain healthy.
- **Next step:** provide and document a supported sandbox backend or narrow the
  sandbox policy deliberately. Do not silently disable the boundary without a
  security review.

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
  replacement and makes libtorrent hash-check them before trusting completion;
  separately reduce the NFS stall that causes the bad shutdowns.
