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
  was submitted.
- **Risk:** traffic that crosses between the router/Wi-Fi side and the wired
  homelab appears to hang even when the NAS and wired switch fabric are healthy.
  Operator SMB access can still be slow, and the same failure can block both
  the normal PR approval path and remote GitOps recovery. OpenClaw remains off
  so its separate read storm does not obscure this test.
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
  timed out while this activity continued.
- **Risk:** hot OpenClaw gateway state, memory indexing, or workspace scanning
  on the QNAP-backed PVC can amplify storage pressure and obscure independent
  network faults.
- **Next step:** after fixing the router/switch uplink, reproduce the OpenClaw
  load in a controlled window and identify which gateway state path is being
  scanned. Keep durable agent state on the PVC, but move any rebuildable hot
  index, cache, or watcher-heavy state to pod-local storage through reviewed
  GitOps desired state if the read storm returns.

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
  the broken state file as `session.state.broken-20260615T040836Z`.
- **Risk:** Deluge can be unavailable while Kubernetes readiness, Gluetun, and
  Argo CD still look healthy, and the same persisted-state corruption may
  recur after future pod or daemon restarts.
- **Next step:** investigate a durable fix for recurring Deluge
  `session.state` corruption, such as a safer shutdown path, a newer Deluge or
  libtorrent image, or an automated guarded recovery that preserves
  `/config/state/*.torrent` and `/downloads`.
