# Tailnet And App Ingress

Tags: #runbook #networking #ingress

Canonical runbook: [`docs/networking-tailnet-ingress.md`](../../networking-tailnet-ingress.md)

Octelium owns primary human-app and callback access. Tailscale remains a
secondary LAN and egress utility. Public callbacks must stay explicit,
path-limited, and represented in repository-owned Istio and tunnel config.

The Tailscale operator and managed exit-node proxy are pinned to `1.102.3`.
When an exit-node client loses DNS through a timed-out PeerAPI `/dns-query`
listener, apply the pinned operator/proxy upgrade through the `tailscale` Argo
CD app, then reconnect the client and repeat the canonical exit-node checks.

See [[octelium]] and [[../workloads/inventory]].
