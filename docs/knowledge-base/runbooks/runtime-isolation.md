# Runtime Isolation

Tags: #runbooks #security #pod-security #network-policy

Source: `docs/runtime-isolation.md`

## Current Boundary

The 2026-05-24 audit found kube-flannel as the only CNI DaemonSet. Flannel does
not enforce Kubernetes `NetworkPolicy`, so `NetworkPolicy` manifests are
documentation placeholders until an enforcing CNI or policy engine exists.

Current enforced controls:

- tailnet-only Istio ingress routes;
- workload-scoped Istio policy only where namespace mesh enrollment is proven;
- explicit namespace Pod Security labels.

## Privileged Namespaces

| Namespace | Reason |
| --- | --- |
| `media` | Deluge Gluetun needs `NET_ADMIN` and `/dev/net/tun` |
| `istio-system` | Istio gateway and dataplane networking |
| `tailscale` | Tailscale operator proxy Pods need privileged networking |

## Baseline Namespaces

`argocd`, `cert-manager`, `external-secrets`, `ai`, `automation`, `finance`,
`monitoring`, and `storage` are explicitly baseline in repo-owned namespace
manifests. `finance` is not mesh-enrolled; Hummingbot's current route is a
tailnet status page, not a service-to-service or trading API path.

## Network Policy Gate

Before expecting `NetworkPolicy` enforcement, first add a repo-owned enforcing
CNI migration or policy-engine installation with rollback notes. After that,
start with namespace default-deny policies and add narrow allow rules for DNS,
ingress gateway traffic, metrics, and app dependencies.
