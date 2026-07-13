# Tailnet And App Ingress

Tags: #runbook #networking #ingress

Canonical runbook: [`docs/networking-tailnet-ingress.md`](../../networking-tailnet-ingress.md)

Octelium owns primary human-app and callback access. Tailscale remains a
secondary LAN and egress utility. Public callbacks must stay explicit,
path-limited, and represented in repository-owned Istio and tunnel config.

See [[octelium]] and [[../workloads/inventory]].
