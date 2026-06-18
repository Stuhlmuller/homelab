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

- Octelium app access through the Istio ingress gateway and reviewed webhook
  Funnel exceptions in `docs/networking-tailnet-ingress.md`;
- workload-scoped Istio policy only where the namespace is explicitly
  mesh-enrolled and the gateway path is proven to keep working;
- namespace Pod Security labels that are explicit in repo-owned namespace
  manifests.

Non-privileged runtime namespaces use the `baseline` Pod Security profile so
new workloads cannot silently add privileged containers, host networking,
hostPath mounts, or other host-level access. Move a namespace to `privileged`
only with the documented justification and owner below. These namespaces warn
and audit against the stricter `restricted` profile so future chart changes
surface before becoming production assumptions.

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
- `octelium-client` is ambient-enrolled so future connector-served upstreams
  have a stable service-account principal. Current app Services forward through
  generated Octelium service proxies into the Istio ingress gateway.

The current service access contract is:

| Destination workload | Namespace | Allowed source principal | Reason |
|----------------------|-----------|--------------------------|--------|
| `litellm` | `ai` | `cluster.local/ns/istio-system/sa/istio-ingressgateway` | Octelium service-proxy app access through the Istio gateway. |
| `litellm` | `ai` | `cluster.local/ns/ai/sa/openclaw` | OpenClaw model gateway calls. |
| `litellm` | `ai` | `cluster.local/ns/octelium-client/sa/octelium-client` | Octelium private service bridge. |
| `openclaw` | `ai` | `cluster.local/ns/istio-system/sa/istio-ingressgateway` | Octelium service-proxy app access through the Istio gateway. |
| `openclaw` | `ai` | `cluster.local/ns/octelium-client/sa/octelium-client` | Octelium private service bridge. |
| `openclaw` | `ai` | `cluster.local/ns/monitoring/sa/prometheus-kube-prometheus-alertmanager` | Alertmanager direct `/hooks/agent` delivery. |
| `n8n` | `automation` | `cluster.local/ns/istio-system/sa/istio-ingressgateway` | Octelium service-proxy app access and reviewed n8n webhook Funnel traffic forwarded through the Istio gateway. |
| `n8n` | `automation` | `cluster.local/ns/octelium-client/sa/octelium-client` | Octelium private service bridge. |
| `grafana` | `monitoring` | `cluster.local/ns/istio-system/sa/istio-ingressgateway` | Octelium service-proxy app access through the Istio gateway. |
| `grafana` | `monitoring` | `cluster.local/ns/monitoring/sa/kiali-service-account` | Kiali dashboard links and health checks. |
| `grafana` | `monitoring` | `cluster.local/ns/monitoring/sa/prometheus-kube-prometheus-prometheus` | Prometheus scrapes Grafana metrics. |
| `grafana` | `monitoring` | `cluster.local/ns/octelium-client/sa/octelium-client` | Octelium private service bridge. |
| `kiali` | `monitoring` | `cluster.local/ns/istio-system/sa/istio-ingressgateway` | Octelium service-proxy app access through the Istio gateway. |
| `kiali` | `monitoring` | `cluster.local/ns/monitoring/sa/prometheus-kube-prometheus-prometheus` | Prometheus scrape or health access. |
| `kiali` | `monitoring` | `cluster.local/ns/octelium-client/sa/octelium-client` | Octelium private service bridge. |
| `compass` | `monitoring` | `cluster.local/ns/istio-system/sa/istio-ingressgateway` | Octelium service-proxy app access through the Istio gateway. |
| `compass` | `monitoring` | `cluster.local/ns/monitoring/sa/prometheus-kube-prometheus-prometheus` | Prometheus scrape access. |
| `compass` | `monitoring` | `cluster.local/ns/octelium-client/sa/octelium-client` | Octelium private service bridge. |
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

`n8n-postgres` has a repository-owned `NetworkPolicy` that allows PostgreSQL
traffic only from pods labeled `app.kubernetes.io/name=n8n`. Because the
current CNI does not enforce `NetworkPolicy`, treat that policy as desired
intent until a repo-owned enforcing dataplane or matching Istio authorization
policy is added and validated.

Ambient is intentionally not enabled for:

- `media`, because Deluge Gluetun/WireGuard and the current media app traffic
  model still need a repo-owned waypoint or equivalent policy design before
  re-enrollment;
- `finance`, because OctoBot needs a separate identity-policy design before any
  service-to-service or trading API control path is mesh-enrolled;
- `argocd`, `cert-manager`, `external-secrets`, and `storage`, because their
  API server, webhook, NFS, and controller paths need separate validation;
- `istio-system`, `octelium`, `octelium-client`, and `tailscale`, because they
  are privileged networking infrastructure rather than ordinary application
  namespaces.

## Privileged Workloads

Privileged Pod Security admission must stay narrow and justified near the
workload that needs it.

| Namespace | Reason | Desired-state owner |
|-----------|--------|---------------------|
| `media` | Deluge Gluetun needs `NET_ADMIN` and `/dev/net/tun` for WireGuard. | `clusters/homelab/apps/deluge/namespace.yaml` |
| `github-actions-runner` | The self-hosted CI runner uses host networking so Octelium gateway hostnames and the Istio ingress gateway ClusterIP are reachable from GitHub Actions jobs; containers remain non-privileged. | `clusters/homelab/apps/github-actions-runner/namespace.yaml` |
| `istio-system` | Istio gateway and dataplane components need elevated networking permissions. | `clusters/homelab/apps/istio/namespace.yaml` |
| `octelium` | Octelium data-plane gateway pods need host networking, hostPath CNI access, and `NET_ADMIN`/`NET_RAW`. | `scripts/octelium-cluster-bootstrap.sh` |
| `octelium-client` | Octelium connector pods need `NET_ADMIN` and `MKNOD` to create `/dev/net/tun` and serve app Services over a real TUN interface. | `clusters/homelab/apps/octelium/namespace.yaml` |
| `tailscale` | Tailscale operator proxy Pods need privileged networking for connector and load-balancer devices. | `clusters/homelab/apps/tailscale/namespace.yaml` |

## Baseline Workloads

These namespaces are explicitly kept at the Pod Security `baseline` profile:

| Namespace | Desired-state owner |
|-----------|---------------------|
| `cert-manager` | `clusters/homelab/apps/cert-manager/namespace.yaml` |
| `external-secrets` | `clusters/homelab/apps/external-secrets/namespace.yaml` |
| `ai` | `clusters/homelab/apps/litellm/namespace.yaml` |
| `argocd` | `clusters/homelab/argocd/self-management/namespace.yaml` |
| `automation` | `clusters/homelab/apps/n8n/namespace.yaml` |
| `finance` | `clusters/homelab/apps/octobot/namespace.yaml` |
| `monitoring` | `clusters/homelab/apps/prometheus/namespace.yaml` |
| `storage` | `clusters/homelab/platform/storage/namespace.yaml` |

Do not broaden privileged admission for convenience. If another workload needs
privileged mode, add the reason, owner, rollback note, and safer alternatives in
the same PR as the manifest change.

Security audit note from 2026-05-25: `media` is broader than ideal because
Sonarr, Radarr, Prowlarr, and media PostgreSQL share the namespace with the
Deluge VPN Pod that needs `/dev/net/tun`. Do not add more privileged workloads
to `media`. The long-term hardening path is to move Deluge and its shared
downloads contract into a dedicated privileged namespace or replace the VPN
pattern with one that does not require privileged namespace admission.

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
