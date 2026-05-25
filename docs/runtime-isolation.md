# Runtime Isolation

This repo treats runtime isolation as desired state, not as an ad hoc live
cluster repair. Add or change isolation controls in git first, validate the
rendered manifests, then let Argo CD converge them.

## Current Boundary

The live audit on 2026-05-24 found kube-flannel as the only CNI DaemonSet.
Flannel provides pod networking, but it does not enforce Kubernetes
`NetworkPolicy`. Until this repo installs an enforcing CNI or a dedicated
policy engine, `NetworkPolicy` objects are documentation placeholders rather
than a reliable isolation control.

Current enforced controls are therefore:

- tailnet-only Istio ingress routes reviewed in
  `docs/networking-tailnet-ingress.md`;
- workload-scoped Istio policy where ambient mesh covers the workload, such as
  Deluge's `PeerAuthentication` and `AuthorizationPolicy`;
- namespace Pod Security labels that are explicit in repo-owned namespace
  manifests.

## Privileged Workloads

Privileged Pod Security admission must stay narrow and justified near the
workload that needs it.

| Namespace | Reason | Desired-state owner |
|-----------|--------|---------------------|
| `media` | Deluge Gluetun needs `NET_ADMIN` and `/dev/net/tun` for WireGuard. | `clusters/homelab/apps/deluge/namespace.yaml` |
| `istio-system` | Istio gateway and dataplane components need elevated networking permissions. | `clusters/homelab/apps/istio/namespace.yaml` |
| `tailscale` | Tailscale operator proxy Pods need privileged networking for connector and load-balancer devices. | `clusters/homelab/apps/tailscale/namespace.yaml` |

Do not broaden privileged admission for convenience. If another workload needs
privileged mode, add the reason, owner, rollback note, and safer alternatives in
the same PR as the manifest change.

## Network Policy Placeholder

Before adding `NetworkPolicy` manifests that are expected to enforce traffic,
first add one of these repo-owned prerequisites:

- a CNI migration plan to a policy-enforcing CNI, with rollback notes; or
- a policy-engine installation that can enforce equivalent L3/L4 controls.

After enforcement exists, start with namespace default-deny policies and add
the smallest allow rules for DNS, ingress gateway traffic, metrics scraping,
and app-to-app dependencies. The first PR that makes `NetworkPolicy` effective
must include a render check and a live read-only verification plan that proves
denied traffic is actually denied.
