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

GitHub vulnerability alerts must be enabled; Renovate owns security-fix PRs,
while Dependabot automated fixes stay disabled to avoid duplicate PRs. The
organization-policy blocker is tracked below.

## Open Findings

The [[audit-2026-09-04]] records the current audit, OpenClaw config-migration
repair, and newly confirmed NOFX access-boundary failure. The
[[audit-2026-09-02]] records the preceding repository fixes, read-only live
inspection, validation, and remaining blockers. The broader
[[audit-2026-08-30]] records prior live repairs and remediation PRs. Public API
port mapping, image debt, and independent restore proof remain open; older
observations below retain their original dates.

- **Status:** fixed
- **Area:** Talos / `zimaboard-2` recovery
- **Evidence:** On 2026-09-02, the reviewed degraded-recovery gates passed:
  the other three nodes were Ready, the dataplane label was absent, no Pod on
  the worker mounted a PVC, and every Octelium Pod there was terminating.
  Authenticated Talos access showed kubelet health failing for about 171 hours
  with CRI and PLEG timeouts. The bounded reboot stalled at phase 1/10,
  `stopAllPods`, while gracefully stopping kubelet; uptime remained 85.7 days
  after the client timed out, proving the node did not restart. A subsequent
  power-cycle reset uptime and restored healthy kubelet, CRI, and containerd.
- **Risk:** Talos v1.11 has no force reboot mode; its `powercycle` mode skips
  kexec but still performs the same graceful teardown. The 1.28 GiB worker
  remains too small for the Octelium dataplane fleet.
- **Validation:** All four nodes, every non-terminal cluster Pod, and all five
  Pods bound to `zimaboard-2` became Ready. The worker retained no Octelium
  dataplane label. Do not restore that label; use the separately tracked
  dedicated replacement capacity.

- **Status:** partially fixed
- **Area:** software supply chain / immutable artifacts
- **Evidence:** The privileged Cordium local-path provisioner now resolves
  Rancher release `v0.0.36` to exact upstream commit
  `5d4bfc84b32cd9c5f56ed3aba921b1a3924ea2f0`; both runtime images were already
  digest-pinned. cert-manager `v1.20.3` and all five of its runtime image
  digests are staged in one versioned Application input so the protected apply
  changes the chart, CRDs, RBAC, and binaries atomically. Issue `#791` tracks
  the remaining chart/native image pins and continuous SBOM, vulnerability,
  and signature checks.
- **Risk:** Other tag-only generated images can still drift, and CI does not
  yet identify actionable HIGH or CRITICAL image vulnerabilities.
- **Next step:** Complete the remaining image inventory and add the smallest
  continuous scan and exception-expiry gate under issue `#791`.

- **Status:** fixed
- **Area:** Istio ambient / ztunnel readiness
- **Evidence:** Read-only inspection on 2026-08-28 found the `zimaboard-0`
  ztunnel returning 13,872 readiness HTTP 500 responses over 36 hours. Its
  workload manager had one pending workload: the live `octelium-client` pod,
  annotated `ambient.istio.io/redirection=pending`. During node recovery, Istio
  CNI first attached before ztunnel was available. Ztunnel later logged
  `[::1]:15053` bind failures, and CNI logged `::/0` route failures. The cluster
  Pod and Service CIDRs are IPv4-only. Desired state now disables ambient IPv6
  in both CNI and ztunnel, forces the CNI DaemonSet to roll, and explicitly
  enrolls the connector pod so its replacement receives a fresh network
  namespace.
- **Validation:** Read-only verification on 2026-09-05 met the recovery gates
  for `#778`: CNI and ztunnel were fully updated and Ready on all four nodes,
  live IPv6 settings were disabled, Istio was `Synced/Healthy`, and every active
  connector reported redirection `enabled`. Prometheus recorded uninterrupted
  ztunnel readiness and no failed CNI or ztunnel readiness probes for 24 hours.
  Current and retained rotated logs covered that window without readiness
  HTTP 500 or IPv6 bind/route errors. September 6 revalidation found one later,
  unclassified CNI probe miss with continuous Pod readiness and no matching IPv6
  signature; this does not establish recurrence of the original defect. A full
  repeat at September 6 23:01 UTC passed the 24-hour acceptance gate, including
  exact Pod-UID series, complete scrape coverage, zero failed probes, and
  current/rotated log coverage without error signatures. The acceptance hold is
  closed; the earlier transient's cause remains unknown. See [[audit-2026-09-04]].
- **Risk:** Future node recovery can interrupt ambient enrollment. Protected
  workloads depend on the connector's Istio service-account principal.
- **Next step:** After future node recovery, repeat
  [[validation-gates#Istio Ambient Recovery]] and classify any further probe
  failure. Roll back by reverting the desired-state settings
  and letting Argo CD reconcile;
  do not opt the connector out of ambient to bypass readiness failures.

- **Status:** fixed
- **Area:** observability / Grafana startup and security
- **Evidence:** Read-only inspection on 2026-08-27 found Grafana running the
  chart-default `12.3.1` image, one imported dashboard truncated to zero bytes,
  recurring `EOF` provisioning errors, and the known SQLite lock race between
  Grafana's annotation and star migrations. The annotation migration completed
  with `totalUpdated=0`. Desired state now uses maintained Grafana Community
  chart `12.11.2` with Grafana `13.2.0`, where the racing star migration is
  removed, plus the compatible Infinity datasource `4.0.0`. Desired state
  deletes obsolete dashboard datasource rewrites, uses TLS-verified transfers,
  and fails fast so Kubernetes retries the complete download step with fresh
  output instead of accepting or concatenating partial JSON. An idempotent,
  verified, atomic pre-v13 SQLite copy provides a schema-rollback checkpoint
  after the old pod stops and before Grafana 13 starts. The first Grafana 13
  rollout exposed the chart's switch to `GF_PLUGINS_PREINSTALL_SYNC`; the
  Infinity pin now uses its native `plugin-id@version` syntax instead of the
  retired custom-URL syntax that made Grafana exit after startup.
- **Risk:** A persistent Grafana.com outage still blocks remote dashboard
  downloads after retries. Grafana remains single-replica SQLite on NFS.
- **Next step:** Keep the community chart current and retain `Recreate` while
  Grafana uses the single SQLite PVC.

- **Status:** blocked by Cloudflare edge certificate subscription
- **Area:** Cordium / public workspace TLS
- **Evidence:** On 2026-08-27 wildcard DNS resolved
  `tls-audit.cordium.stinkyboi.com`, but both Cloudflare edge addresses closed
  the TLS handshake. The active edge certificate covers only `stinkyboi.com`
  and `*.stinkyboi.com`; Cordium advertises workspace hosts under
  `*.cordium.stinkyboi.com`.
- **Risk:** Cordium's browser entrypoint can authenticate, but generated
  workspace app URLs fail before HTTP routing.
- **Next step:** purchase Cloudflare Advanced Certificate Manager and issue an
  edge certificate containing `*.cordium.stinkyboi.com`, then rerun
  `scripts/octelium-e2e-check.sh`. Total TLS cannot cover Cloudflare Tunnel
  hostnames, so use an explicit advanced wildcard.

- **Status:** superseded by outbound Tunnel transport; rollout verification pending
- **Area:** Octelium / public gRPC transport
- **Evidence:** On 2026-08-28 the public API completed Cloudflare TLS and HTTP/2
  but returned no gRPC response, while direct NodePort `10.1.0.200:30443`
  returned unauthenticated `grpc-status: 16`. The lease CronJob had not
  succeeded since 2026-08-06, and its `zimaboard-1` target became NotReady.
  Desired state moves the existing miniupnpc reconciler to Ready `zimaboard-0`,
  pins the end-to-end gRPC request to a public `1.1.1.1` answer, and alerts when
  the last successful renewal is stale or absent. Live IGD discovery still
  reports no usable UPnP gateway. Read-only checks on 2026-09-02 confirmed the
  public API still times out while the direct LAN origin returns HTTP/2 and
  unauthenticated `grpc-status: 16`; the latest lease Jobs still fail.
- **Risk:** The old WAN path remains unavailable. September 5 operator
  clarification selects Cloudflare Tunnel; the replacement separates browser
  gRPC-Web from native TLS gRPC over a TCP carrier. Do not retire private
  fallback access until authenticated CLI, console, Cordium, and Talos gates
  pass. Long-lived TCP-carrier reconnect behavior remains unverified.
- **Next step:** Sync the reviewed Tunnel routes, run the protected
  `octelium-public-tunnel.yml` DNS/rule reconciliation, then pass
  `scripts/octelium-tunnel-check.py` and authenticated execution tests.
  The UPnP job and lease alert are suspended in desired state. Historical
  router observations above no longer prescribe the current rollout.

- **Status:** fixed
- **Area:** CI/CD / credential isolation
- **Evidence:** On 2026-08-27 `homelab-plan` and `homelab-production` were
  configured with required reviewers, production was limited to `main`,
  repository Actions began enforcing full commit SHA references, and ruleset
  `14700233` began requiring signed squash pull requests, strict always-on
  checks, and non-fast-forward protection. Unused repository secrets
  `KUBE_CONFIG_B64`, `TAILSCALE_AUTH_KEY`, and `TS_AUTH_KEY` were removed.
- **Risk:** A reviewer can still approve their own deployment because the
  organization has one member; the gate provides an explicit diff-review
  checkpoint but not independent separation of duties.
- **Next step:** Keep live credentials environment-scoped and require a second
  reviewer after another trusted organization member exists.

- **Status:** blocked by organization policy and authority
- **Area:** dependency security
- **Evidence:** Organization security configuration `249879` enforces disabled
  dependency graph and Dependabot alerts for this repository. Repository-level
  enablement returns HTTP 422, and the current operator token has `read:org`
  but not `write:org`.
- **Risk:** Renovate cannot consume GitHub vulnerability alerts, so known
  vulnerable dependencies may not produce security-fix pull requests.
- **Next step:** An organization owner should attach a scoped security
  configuration that enables dependency graph and Dependabot alerts for
  `Stuhlmuller/homelab` while leaving Dependabot security updates disabled.

  returned `200` while the protected hostname returned `503`. On September 6,
  Entra login reached Dispatcharr `0.29.0`; first-run setup rejected the
  forwarded public IP. A loopback-only authenticated port-forward allowed the
  read-only setup check. PostgreSQL has no accounts/admins, channels or streams
  and no configured provider beyond the default custom M3U seed. The user
  confirmed the app was never configured. No account was created during these
  checks.
- **Risk:** The service is reachable but first-admin/provider setup and
  functional use remain incomplete.
- **Next step:** Complete human-owned first-admin setup through the documented
  loopback tunnel, then verify protected account login and
  provider/EPG/channel/playback behavior. Preserve both claims and the upstream
  setup-IP restriction. See [[workloads/application-notes#Dispatcharr]].
