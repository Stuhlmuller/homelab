# Octelium

Tags: #runbook #octelium #access

Canonical runbook: [`docs/octelium.md`](../../octelium.md)

Octelium is the primary human-app, private Kubernetes, callback, and CI access
backbone. Operator machines run `octelium connect` and generate a kubeconfig
with `octelium config kubernetes-api.homelab`; Cordium Workspaces already have
their own client session and use the same private Service. Keep Cluster
bootstrap, Enterprise adoption, public Cloudflare routing, Entra OIDC, and the
end-to-end gate on their repository-owned scripts and manifests. The catalog
also owns the core human session ceiling; apply its `ClusterConfig` include
separately before the normal catalog apply.

Bootstrap and upgrade require the dataplane label on `zimaboard-0`, the
control-plane label on `zimaboard-1`, and no dataplane label on `zimaboard-2`.
The bootstrap script refuses to mutate the cluster if these selectors fail,
including a missing node or failed API lookup.

The public API uses outbound Cloudflare Tunnel: HTTPS for browser gRPC-Web
and `octelium-transport.stinkyboi.com` TCP-over-WebSocket for native TLS gRPC.
The old UPnP job is suspended and its lease alert paused. Reconcile DNS and
remove retired origin rules with `octelium-public-tunnel.yml` after Argo sync.
Run `scripts/octelium-tunnel-check.py`; then prove authenticated console,
audit queries, Cordium execution, and reconnect behavior separately. Native
clients need a scoped canonical API resolver mapping and local carrier;
workstation-wide hosts overrides would also redirect browser API requests.

The temporary August 2026 recovery manifest runs the control paths, CI API,
and 18 additional public WEB Service fallbacks on `acer` without Multus, 19
including the existing OctoBot fallback. Its generated Service UIDs must be
refreshed after any Service recreation. Keep it until the native fleet passes
the capacity, 24-hour stability, direct Pod, and public end-to-end removal
gates in [[../architecture/cluster-topology]].

See [[../architecture/secrets-and-identity]], [[tailnet-ingress]], and
[[../workloads/inventory]].

## macOS API carrier

`scripts/octelium-macos-api-carrier.py` installs a loopback-only native API
carrier as a system LaunchDaemon. macOS requires administrator permission for
its port 443 listener. The installer checks TLS, native gRPC, and browser
gRPC-Web before adding one marked canonical API hostname entry to `/etc/hosts`;
public DNS remains unchanged. It rejects conflicting local hostname entries or
listeners, preserves unrelated hosts entries, and provides an uninstall path.
The macOS curl status-line trailing-space regression is covered by the offline
check in `scripts/ci/octelium-macos-api-carrier-test.py`.

On 2026-10-01 both protocol probes, privileged installation, authenticated
native status, private Multica HTTP 200, and desktop runtime refresh passed on
the home LAN. `scripts/multica-desktop-connect.py` owns the user LaunchAgent and
backed-up desktop HTTP/WebSocket endpoint configuration. It starts at login and
restarts failed clients. Off-LAN and new chat-send acceptance remain separate
checks. This carrier grants no Octelium permissions and does not
bypass session expiry. See [the macOS setup procedure](../../octelium.md).


### Gateway retirement finding

The 2026-10-01 authenticated Gateway inventory still included `zimaboard-2`
after its dataplane label was removed; only `zimaboard-0` ran a gateway agent.
Upstream v0.35.0 nocturne removes a Gateway when its Node disappears, but label
removal does not trigger that cleanup. The home-LAN connection succeeded with
this inventory; its effect on reconnect latency is unproven. Add a validated,
repository-owned retirement path before removing the stale Gateway; do not
delete the Kubernetes Node merely to force cleanup.
