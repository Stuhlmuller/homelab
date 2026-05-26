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
- workload-scoped Istio policy only where the namespace is explicitly
  mesh-enrolled and the gateway path is proven to keep working;
- namespace Pod Security labels that are explicit in repo-owned namespace
  manifests.

Non-privileged runtime namespaces use the `baseline` Pod Security profile so
new workloads cannot silently add privileged containers, host networking,
hostPath mounts, or other host-level access. Move a namespace to `privileged`
only with the documented justification and owner below.

## Istio Ambient Service Access

Istio ambient is enabled in the app namespaces where the current traffic graph
is known well enough to enforce with Layer 4 identity policy:

- `ai` has a namespace default-deny `AuthorizationPolicy`; only the explicit
  workload allow rules below should accept inbound mesh traffic.
- `automation` and `monitoring` are ambient-enrolled, but enforcement starts
  with selected workload policies instead of a namespace default-deny. Policy
  Bot Funnel traffic, monitoring operator webhooks, and other controller paths
  need live source-identity validation before those namespaces move to full
  default-deny.

The current service access contract is:

| Destination workload | Namespace | Allowed source principal | Reason |
|----------------------|-----------|--------------------------|--------|
| `litellm` | `ai` | `cluster.local/ns/istio-system/sa/istio-ingressgateway` | Tailnet UI/API ingress. |
| `litellm` | `ai` | `cluster.local/ns/ai/sa/openclaw` | OpenClaw model gateway calls. |
| `openclaw` | `ai` | `cluster.local/ns/istio-system/sa/istio-ingressgateway` | Tailnet UI ingress. |
| `n8n` | `automation` | `cluster.local/ns/istio-system/sa/istio-ingressgateway` | Tailnet UI and webhook ingress through the private gateway. |
| `grafana` | `monitoring` | `cluster.local/ns/istio-system/sa/istio-ingressgateway` | Tailnet UI ingress. |
| `grafana` | `monitoring` | `cluster.local/ns/monitoring/sa/kiali-service-account` | Kiali dashboard links and health checks. |
| `grafana` | `monitoring` | `cluster.local/ns/monitoring/sa/prometheus-kube-prometheus-prometheus` | Prometheus scrapes Grafana metrics. |
| `prometheus` | `monitoring` | `cluster.local/ns/monitoring/sa/grafana` | Grafana Prometheus datasource queries. |
| `prometheus` | `monitoring` | `cluster.local/ns/monitoring/sa/kiali-service-account` | Kiali graph and health queries. |
| `prometheus` | `monitoring` | `cluster.local/ns/monitoring/sa/prometheus-kube-prometheus-prometheus` | Prometheus self-scrape and in-stack access. |
| `alertmanager` | `monitoring` | `cluster.local/ns/monitoring/sa/grafana` | Grafana Alertmanager datasource and contact point. |
| `alertmanager` | `monitoring` | `cluster.local/ns/monitoring/sa/prometheus-kube-prometheus-prometheus` | Prometheus alert delivery. |
| `alertmanager` | `monitoring` | `cluster.local/ns/monitoring/sa/prometheus-kube-prometheus-alertmanager` | Alertmanager peer traffic if replicas increase. |
| `kube-state-metrics` | `monitoring` | `cluster.local/ns/monitoring/sa/prometheus-kube-prometheus-prometheus` | Prometheus metrics scrape. |

These policies are inbound controls on selected destination workloads. They do
not replace egress controls, and they do not make Kubernetes `NetworkPolicy`
effective on flannel. Keep new service-to-service paths out of the mesh until
the source service account, destination selector, and rollback path are
documented in the same change.

Ambient is intentionally not enabled for:

- `media`, because Deluge Gluetun/WireGuard and the current media app traffic
  model still need a repo-owned waypoint or equivalent policy design before
  re-enrollment;
- `finance`, because Hummingbot exposes only a tailnet status page today and
  the trading client needs a separate identity-policy design before any
  service-to-service or API control path is mesh-enrolled;
- `argocd`, `cert-manager`, `external-secrets`, and `storage`, because their
  API server, webhook, NFS, and controller paths need separate validation;
- `istio-system` and `tailscale`, because they are privileged networking
  infrastructure rather than application namespaces.

## Privileged Workloads

Privileged Pod Security admission must stay narrow and justified near the
workload that needs it.

| Namespace | Reason | Desired-state owner |
|-----------|--------|---------------------|
| `media` | Deluge Gluetun needs `NET_ADMIN` and `/dev/net/tun` for WireGuard. | `clusters/homelab/apps/deluge/namespace.yaml` |
| `istio-system` | Istio gateway and dataplane components need elevated networking permissions. | `clusters/homelab/apps/istio/namespace.yaml` |
| `tailscale` | Tailscale operator proxy Pods need privileged networking for connector and load-balancer devices. | `clusters/homelab/apps/tailscale/namespace.yaml` |

## Baseline Workloads

These namespaces are explicitly kept at the Pod Security `baseline` profile:

| Namespace | Desired-state owner |
|-----------|---------------------|
| `argocd` | `clusters/homelab/argocd/self-management/namespace.yaml` |
| `cert-manager` | `clusters/homelab/apps/cert-manager/namespace.yaml` |
| `external-secrets` | `clusters/homelab/apps/external-secrets/namespace.yaml` |
| `ai` | `clusters/homelab/apps/litellm/namespace.yaml` |
| `automation` | `clusters/homelab/apps/n8n/namespace.yaml` |
| `finance` | `clusters/homelab/apps/hummingbot/namespace.yaml` |
| `monitoring` | `clusters/homelab/apps/prometheus/namespace.yaml` |
| `storage` | `clusters/homelab/platform/storage/namespace.yaml` |

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
