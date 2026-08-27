# Octelium

Tags: #runbook #octelium #access

Canonical runbook: [`docs/octelium.md`](../../octelium.md)

Octelium is the primary human-app, callback, and CI access backbone. Keep
Cluster bootstrap, Enterprise adoption, public Cloudflare routing, Entra OIDC,
and the end-to-end gate on their repository-owned scripts and manifests. The
catalog also owns the core human session ceiling; apply its `ClusterConfig`
include separately before the normal catalog apply.

The temporary August 2026 recovery manifest runs the control paths, CI API,
and 18 additional public WEB Service fallbacks on `acer` without Multus, 19
including the existing OctoBot fallback. Its generated Service UIDs must be
refreshed after any Service recreation. Keep it until the native fleet passes
the capacity, 24-hour stability, direct Pod, and public end-to-end removal
gates in [[../architecture/cluster-topology]].

See [[../architecture/secrets-and-identity]], [[tailnet-ingress]], and
[[../workloads/inventory]].
