---
type: runbook
title: "Octelium"
description: "Octelium access ownership, browser gRPC-Web versus native TLS transport, macOS API carrier, and reconnect failure evidence."
tags: ["runbook", "octelium", "access"]
sources:
  - id: openwiki-source-1ab63006818d653aed251f6d
    resource: repo://clusters/homelab/apps/traefik/authorizationpolicy.yaml
  - id: openwiki-source-8f628fd33437cf63e7f9b8c2
    resource: repo://clusters/homelab/apps/traefik/CUTOVER.md
  - id: openwiki-source-ac4e5166b14da067a9c57d03
    resource: repo://clusters/homelab/apps/traefik/networkpolicy.yaml
  - id: openwiki-source-e26a7307e86732ce7e6a34b6
    resource: repo://clusters/homelab/apps/traefik/routes.yaml
  - id: openwiki-source-b3b14c71f8a81de8a3b71c02
    resource: repo://docs/examples/octelium/homelab-services.yaml
  - id: openwiki-source-785c903805cb6f5a9ea9ae91
    resource: repo://docs/octelium.md
  - id: openwiki-source-8f8dab72ff0b7636d31aef4b
    resource: repo://docs/openclaw-enterprise-rollout.md
  - id: openwiki-source-e293d5daa2ad090397b8923e
    resource: repo://scripts/openclaw-enterprise-access.py
  - id: openwiki-source-111e7fc5206f50a28e4daf9c
    resource: repo://specs/005-retire-public-app-dns/contracts/cutover.md
generated: { by: "codex", at: "2026-10-19T15:59:51.049Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-19T22:48:59.937Z
---

# Octelium

Canonical runbook: [`docs/octelium.md`](../../docs/octelium.md)

Octelium application, callback, and CI routes remain during staged Traefik
cutover; its retained role includes Cordium control endpoints and the staged
OpenClaw Enterprise console and authenticated legacy redirect. Preserve
existing operator sessions and `kubernetes-api.homelab` access until replacement
acceptance. Cordium retains its restricted native Kubernetes Service. Cluster
bootstrap, Enterprise adoption, and Entra OIDC stay on their repository-owned
scripts and manifests. The catalog
also owns the core human session ceiling; apply its `ClusterConfig` include
separately before the normal catalog apply.

Bootstrap and upgrade require the dataplane label on `zimaboard-0`, the
control-plane label on `zimaboard-1`, and no dataplane label on `zimaboard-2`.
The bootstrap script refuses to mutate the cluster if these selectors fail,
including a missing node or failed API lookup.

The retained Cloudflare Tunnel provides old browser and native carrier routes
until mesh acceptance. Its DNS-restoration workflow and old DNS writer are
removed in phase 2a. Follow the
[staged cutover](../../clusters/homelab/apps/traefik/CUTOVER.md) for guarded
tailnet resolver handoff, later public-record retirement, Mac migration,
callback delivery, and later CI transport.
The resolver approves 29 current names; the later public retirement selects
only the 26 non-apex names from the fixed original migration set.
Require canonical TLS, native gRPC/gRPC-Web, authenticated console access, and
actual Cordium execution/reconnection before removing the old tunnel or catalog.
The legacy `octelium-tunnel-check.py` is not a mesh acceptance gate.

During the CoreDNS rewrite, Traefik's private listener explicitly admits the
retained `cluster.local/ns/octelium-client/sa/octelium-client` principal only on
8443. Confirm its authenticated API requests after reconciliation. The allowance
and matching intended NetworkPolicy selector retire with the connector, not
before it. New application routes belong in Traefik; the retained Octelium
catalog is not a recipe to restore public app DNS or delete Cordium resources.

## OpenClaw Enterprise access staging

The [reviewed catalog](../../docs/examples/octelium/homelab-services.yaml)
adds Namespace `oce`, authenticated Service `console.oce`, and a
post-authentication 303 redirect in `openclaw.default`. The console proxies to
the Enterprise API after Octelium human authorization; the old Traefik
`openclaw.stinkyboi.com` route still points at the suspended legacy Service
until final cutover. The scoped
[`openclaw-enterprise-access.py`](../../scripts/openclaw-enterprise-access.py)
reconciler checks clean exact current `main`, applies only those three catalog
objects, verifies a no-change second apply, and reads back authorization and
redirect state. This is staged source, not a live reconciliation receipt.

OCE creates opaque per-Agent hosts that fixed Octelium Service names cannot
represent. Only `agent-<32 hex>.agents.oce.stinkyboi.com` goes from the
Tailscale-only Traefik listener directly to the OCE API. OCE enforces the
authenticated session and exact Agent permission before reaching private
Envoy. See [private ingress](tailnet-ingress.md) and the
[Enterprise rollout](../../docs/openclaw-enterprise-rollout.md).

The temporary August 2026 recovery manifest runs the control paths, CI API,
and 18 public WEB Service fallbacks on `acer` without Multus. Its generated Service UIDs must be
refreshed after any Service recreation. Keep it until the native fleet passes
the capacity, 24-hour stability, direct Pod, and public end-to-end removal
gates in [Cluster Topology](../architecture/cluster-topology.md).

See [Secrets And Identity](../architecture/secrets-and-identity.md), [Tailnet And App Ingress](tailnet-ingress.md), and
[Workload Inventory](../workloads/inventory.md).

## macOS API carrier

Before the retained ingress preflight, `multica-desktop-connect.py --resume-only` reconnects the
verified saved Tailscale profile without changing Desktop or its carrier. After
the owner tailnet DNS setting passes normal client checks, the full migration preserves Desktop credentials and
removes only owned transports after authenticated canonical API checks.

The retained `scripts/octelium-macos-api-carrier.py install` supports reviewed
rollback to the loopback API carrier. macOS requires administrator permission for
its port 443 listener. The installer checks TLS, native gRPC, and browser
gRPC-Web before adding one marked canonical API hostname entry to `/etc/hosts`;
public DNS remains unchanged. It rejects conflicting local hostname entries or
listeners, preserves unrelated hosts entries, and provides an uninstall path.
The macOS curl status-line trailing-space regression is covered by the offline
check in `scripts/ci/octelium-macos-api-carrier-test.py`.

On 2026-10-01 both protocol probes, privileged installation, authenticated
native status, private Multica HTTP 200, and desktop runtime refresh passed on
the home LAN. `scripts/multica-desktop-connect.py` owns the user LaunchAgent and
backed-up desktop HTTP/WebSocket endpoint configuration. At that time it installed
login startup and client restart behavior; the current helper migrates that owned
state. Off-LAN and new chat-send acceptance remain separate
checks. This carrier grants no Octelium permissions and does not
bypass session expiry. See [the macOS setup procedure](../../docs/octelium.md).


### Gateway retirement finding

The 2026-10-01 authenticated Gateway inventory still included `zimaboard-2`
after its dataplane label was removed; only `zimaboard-0` ran a gateway agent.
Upstream v0.35.0 nocturne removes a Gateway when its Node disappears, but label
removal does not trigger that cleanup. The home-LAN connection succeeded with
this inventory; its effect on reconnect latency is unproven. Add a validated,
repository-owned retirement path before removing the stale Gateway; do not
delete the Kubernetes Node merely to force cleanup.


The follow-up failure on 2026-10-01 was a running native client with no local
listener, while the API carrier and authenticated session remained healthy.
Restarting that client restored HTTP 200. Process-only `KeepAlive` cannot catch
this state. The installed supervisor checks HTTP every five seconds, allows 90
seconds for startup and 30 seconds of sustained failure after readiness, then
reaps the client so launchd can restart it. Session expiration still requires
login; the original client hang trigger remains unknown. The supervisor is
copied into `~/.multica/octelium-client.py`, independent of worktree lifetime.

A live acceptance test froze only the managed client with SIGSTOP. The
supervisor reaped it, launchd restarted the connection, HTTP returned 200, and
the same desktop Autopilot page recovered to show 13 entries without an app
restart. The offline regression exercises a running but unresponsive child.
