# Tailnet And App Ingress

Tags: #runbook #networking #ingress

Canonical runbook: [`docs/networking-tailnet-ingress.md`](../../networking-tailnet-ingress.md)

Octelium owns primary human-app, Kubernetes, Cordium, and callback access. The
primary Istio gateway is `ClusterIP` only. Tailscale remains deployed as a
temporary Talos/LAN/egress fallback; remove it only after the private Octelium
Kubernetes paths and a replacement Talos transport are validated remotely.
Public callbacks must stay explicit, path-limited, and represented in
repository-owned Istio and tunnel config.

See [[octelium]] and [[../workloads/inventory]].
