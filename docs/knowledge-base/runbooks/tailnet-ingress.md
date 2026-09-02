# Octelium Access And Tailscale Exit Egress

Tags: #runbook #networking #ingress

Canonical runbook: [`docs/networking-tailnet-ingress.md`](../../networking-tailnet-ingress.md)

Octelium owns primary human-app, Kubernetes, Cordium, and callback access. The
primary Istio gateway is `ClusterIP` only. Tailscale remains deployed only as
an outbound exit-node VPN and advertises no homelab subnet. Remote Talos access
uses the owner-only `talos-api.homelab` Octelium Service; direct IP remains a
local-LAN recovery path.
Public callbacks must stay explicit, path-limited, and represented in
repository-owned Istio and tunnel config.

See [[octelium]] and [[../workloads/inventory]].
