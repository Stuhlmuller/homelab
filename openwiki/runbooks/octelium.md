---
type: runbook
title: "Octelium"
description: "Octelium access ownership, browser gRPC-Web versus native TLS transport, macOS API carrier, and reconnect failure evidence."
tags: ["runbook", "octelium", "access"]
sources:
  - id: openwiki-source-8f628fd33437cf63e7f9b8c2
    resource: repo://clusters/homelab/apps/traefik/CUTOVER.md
  - id: openwiki-source-785c903805cb6f5a9ea9ae91
    resource: repo://docs/octelium.md
  - id: openwiki-source-0f0f64f89adebd3b517b3c98
    resource: repo://scripts/multica-desktop-connect.py
generated: { by: "codex", at: "2026-10-10T22:12:32.276Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-10T23:03:36.138Z
---

# Octelium

Canonical runbook: [`docs/octelium.md`](../../docs/octelium.md)

Octelium application, callback, and CI routes remain during staged Traefik
cutover; final ownership is Cordium and its required control endpoints. Preserve
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
DNS-only mesh records, Mac migration, callback delivery, and later CI transport.
Require canonical TLS, native gRPC/gRPC-Web, authenticated console access, and
actual Cordium execution/reconnection before removing the old tunnel or catalog.
The legacy `octelium-tunnel-check.py` is not a mesh acceptance gate.

The temporary August 2026 recovery manifest runs the control paths, CI API,
and 18 additional public WEB Service fallbacks on `acer` without Multus, 19
including the existing OctoBot fallback. Its generated Service UIDs must be
refreshed after any Service recreation. Keep it until the native fleet passes
the capacity, 24-hour stability, direct Pod, and public end-to-end removal
gates in [Cluster Topology](../architecture/cluster-topology.md).

See [Secrets And Identity](../architecture/secrets-and-identity.md), [Tailnet And App Ingress](tailnet-ingress.md), and
[Workload Inventory](../workloads/inventory.md).

## macOS API carrier

Before DNS preflight, `multica-desktop-connect.py --resume-only` reconnects the
verified saved Tailscale profile without changing Desktop or its carrier. After
private DNS is written, the full migration preserves Desktop credentials and
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
