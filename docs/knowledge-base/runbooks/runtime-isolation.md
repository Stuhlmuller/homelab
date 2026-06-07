# Runtime Isolation

Tags: #runbooks #security #pod-security #network-policy

Source: `docs/runtime-isolation.md`

## Current Boundary

The 2026-05-24 audit found kube-flannel as the only CNI DaemonSet. Flannel does
not enforce Kubernetes `NetworkPolicy`, so `NetworkPolicy` manifests are
documentation placeholders until an enforcing CNI or policy engine exists.

Current enforced controls:

- Octelium service-proxy access to app UIs through the Istio gateway;
- workload-scoped Istio policy only where namespace mesh enrollment is proven;
- explicit namespace Pod Security labels.

## Privileged Namespaces

| Namespace | Reason |
| --- | --- |
| `media` | Deluge Gluetun needs `NET_ADMIN` and `/dev/net/tun` |
| `istio-system` | Istio gateway and dataplane networking |
| `octelium` | Octelium data-plane gateway pods need host networking, hostPath CNI access, and `NET_ADMIN`/`NET_RAW`; labels are applied by `scripts/octelium-cluster-bootstrap.sh` after `octops` creates the namespace |
| `octelium-client` | Octelium connector pods need `NET_ADMIN` and `MKNOD` to create `/dev/net/tun` and serve app Services over a real TUN interface |
| `tailscale` | Tailscale operator proxy Pods need privileged networking |

## Baseline Namespaces

`argocd`, `cert-manager`, `external-secrets`, `ai`, `automation`, `finance`,
`monitoring`, `octelium-client`, and `storage` are explicitly baseline in
repo-owned namespace manifests. `octelium-client` is ambient-enrolled so the
Octelium connector can be allowed as
`cluster.local/ns/octelium-client/sa/octelium-client` by protected workloads.
`finance` is not mesh-enrolled; OctoBot's UI is reached through the Octelium
service-proxy path and does not expose trading API access directly.

## Network Policy Gate

Before expecting `NetworkPolicy` enforcement, first add a repo-owned enforcing
CNI migration or policy-engine installation with rollback notes. After that,
start with namespace default-deny policies and add narrow allow rules for DNS,
ingress gateway traffic, metrics, and app dependencies.

`n8n-postgres` now includes a NetworkPolicy that documents n8n-only PostgreSQL
access in the `automation` namespace. It is desired-state intent, not an
enforced boundary, until the NetworkPolicy gate above is satisfied or an Istio
authorization policy for the database path is added and validated.

Octelium-serving paths use Istio `AuthorizationPolicy` for ambient-enrolled
destinations and Kubernetes `NetworkPolicy` intent for workloads that already
have NetworkPolicy manifests. The Octelium connector should stay scoped to the
explicit service catalog in `docs/examples/octelium/homelab-services.yaml`.
