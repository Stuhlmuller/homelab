# Runtime Isolation

<!-- markdownlint-disable MD060 -->

This repo treats runtime isolation as desired state, not as an ad hoc live
cluster repair. Add or change isolation controls in git first, validate the
rendered manifests, then let Argo CD converge them.

## Current Boundary

The live audit on 2026-05-24 found kube-flannel as the only CNI DaemonSet.
Flannel provides pod networking, but it does not enforce Kubernetes
`NetworkPolicy`. The firewall-only kube-router source is staged with automatic
sync disabled and no admitted node; until it passes the canary gates below,
`NetworkPolicy` objects are documentation placeholders rather than a reliable
isolation control.

Current enforced controls are therefore:

- Octelium app access and reviewed public callback routes through the
  `octelium-public` tunnel and Istio ingress gateway, as documented in
  `docs/networking-tailnet-ingress.md`;
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
- `affine` has a namespace default-deny policy, allows the Istio gateway to the
  server, and allows only the `affine` service account to reach its PostgreSQL
  and Redis pods.
- `automation` and `monitoring` are ambient-enrolled, but enforcement starts
  with selected workload policies instead of a namespace default-deny. Policy
  Bot callback traffic, monitoring operator webhooks, and other controller
  paths need live source-identity validation before those namespaces move to
  full default-deny.
- `octelium-client` is ambient-enrolled so future connector-served upstreams
  have a stable service-account principal. Current app Services forward through
  generated Octelium service proxies into the Istio ingress gateway.

The current service access contract is:

| Destination workload | Namespace | Allowed source principal | Reason |
|----------------------|-----------|--------------------------|--------|
| `affine` | `affine` | `cluster.local/ns/istio-system/sa/istio-ingressgateway` | Public Octelium transport with AFFiNE-owned authentication through the Istio gateway. |
| `affine` | `affine` | `cluster.local/ns/octelium-client/sa/octelium-client` | Octelium private service bridge. |
| `affine-postgres`, `affine-redis` | `affine` | `cluster.local/ns/affine/sa/affine` | AFFiNE server and migration access to dedicated state services. |
| `litellm` | `ai` | `cluster.local/ns/istio-system/sa/istio-ingressgateway` | Octelium service-proxy app access through the Istio gateway. |
| `litellm` | `ai` | `cluster.local/ns/ai/sa/openclaw` | OpenClaw model gateway calls. |
| `litellm` | `ai` | `cluster.local/ns/octelium-client/sa/octelium-client` | Octelium private service bridge. |
| `openclaw` | `ai` | `cluster.local/ns/istio-system/sa/istio-ingressgateway` | Octelium service-proxy app access through the Istio gateway. |
| `openclaw` | `ai` | `cluster.local/ns/octelium-client/sa/octelium-client` | Octelium private service bridge. |
| `openclaw` | `ai` | `cluster.local/ns/monitoring/sa/prometheus-kube-prometheus-alertmanager` | Alertmanager direct `/hooks/agent` delivery. |
| `n8n` | `automation` | `cluster.local/ns/istio-system/sa/istio-ingressgateway` | Octelium service-proxy app access and reviewed n8n webhook callback traffic forwarded through the Istio gateway. |
| `n8n` | `automation` | `cluster.local/ns/octelium-client/sa/octelium-client` | Octelium private service bridge. |
| `n8n` | `automation` | `cluster.local/ns/automation/sa/n8n` | Authenticated n8n workflows calling the same instance through its in-cluster Service. |
| `grafana` | `monitoring` | `cluster.local/ns/ai/sa/openclaw` | Authenticated homelab monitoring through Grafana datasource queries. |
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

- `langfuse`, because its dedicated single-node data stores use the ordinary
  Kubernetes service path; mesh enrollment needs a complete store-to-web/worker
  identity policy and rollback plan;
- `media`, because Deluge Gluetun/WireGuard and the current media app traffic
  model still need a repo-owned waypoint or equivalent policy design before
  re-enrollment;
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
| `istio-system` | Istio gateway and dataplane components need elevated networking permissions. | `clusters/homelab/apps/istio/namespace.yaml` |
| `octelium` | Octelium data-plane gateway pods need host networking, hostPath CNI access, and `NET_ADMIN`/`NET_RAW`. | `scripts/octelium-cluster-bootstrap.sh` |
| `octelium-client` | Octelium connector pods need `NET_ADMIN` and `MKNOD` to create `/dev/net/tun` and serve app Services over a real TUN interface. | `clusters/homelab/apps/octelium/namespace.yaml` |
| `cordium` | Cordium-generated Workspace Pods run as privileged root containers with an unconfined AppArmor profile. | `clusters/homelab/apps/cordium/namespace.yaml` |
| `tailscale` | The Tailscale exit-node Connector proxy needs privileged networking. | `clusters/homelab/apps/tailscale/namespace.yaml` |

## Baseline Workloads

These namespaces are explicitly kept at the Pod Security `baseline` profile:

| Namespace | Desired-state owner |
|-----------|---------------------|
| `affine` | `clusters/homelab/apps/affine/namespace.yaml` |
| `cert-manager` | `clusters/homelab/apps/cert-manager/namespace.yaml` |
| `external-secrets` | `clusters/homelab/apps/external-secrets/namespace.yaml` |
| `ai` | `clusters/homelab/apps/litellm/namespace.yaml` |
| `argocd` | `clusters/homelab/argocd/self-management/namespace.yaml` |
| `automation` | `clusters/homelab/apps/n8n/namespace.yaml` |
| `langfuse` | `clusters/homelab/apps/langfuse/namespace.yaml` |
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

## Staged NetworkPolicy enforcement

[`clusters/homelab/platform/network-policy/`](../clusters/homelab/platform/network-policy/README.md)
owns the pinned kube-router firewall DaemonSet, isolated canary fixtures and
ownership-limited cleanup. It leaves Flannel as the CNI and kube-proxy as the
service proxy. The Argo registrations are dormant; no node is selected or
tainted. The [policy review](evidence/openclaw-enterprise-policy-review.json)
still has unqualified source-bound generated policies and broad egress findings. The
[acceptance ledger](evidence/openclaw-enterprise-acceptance.md) records why no
existing node safely admits the isolated canary.

The three Cordium Genesis policies have a [read-only expected-spec fixture](../clusters/homelab/apps/cordium-bootstrap/generated-networkpolicies.json)
for `cordium/ws-main`, `octelium/cordium-nocturne`, and
`octelium/cordium-rscserver`. Their complete specs match the live read-only
recheck and the constructors in pinned [Cordium v0.12.7](https://github.com/octelium/cordium/tree/e12b0b16d5fe94716e414fca7cfdc10b21014f2c/cluster/genesis/genesis).
Pass this fixture as an additional `--render` input when auditing Cordium and
Octelium; it is not applied by Kustomize. `ws-main` still allows every port to
public IPv4/IPv6 ranges after private-range exclusions, so its strict broad
egress finding and canary traffic review remain open.

Four Octelium Genesis policies have a separate [v0.35.0 expected-spec fixture](../clusters/homelab/apps/octelium/generated-networkpolicies.json)
based on the pinned [constructors](https://github.com/octelium/octelium/tree/5e4eb3e36911ba4f66f5f43df2cc4b264211c4ce/cluster/genesis/genesis/components).
Their complete specs matched a fresh read-only live check on October 20.
Pass that fixture as another `--render` input; it is not a deployed owner.
`octelium/svc-upstream` still allows all ports to public IPv4/IPv6 ranges,
so source binding does not qualify its traffic.

The pinned [Cordium constructor](https://github.com/octelium/cordium/blob/e12b0b16d5fe94716e414fca7cfdc10b21014f2c/cluster/genesis/genesis/ws_init.go#L254-L345)
and [non-dev Genesis write](https://github.com/octelium/cordium/blob/e12b0b16d5fe94716e414fca7cfdc10b21014f2c/cluster/genesis/genesis/ws_init.go#L64-L71),
plus [Octelium's constructor and unconditional install](https://github.com/octelium/octelium/blob/5e4eb3e36911ba4f66f5f43df2cc4b264211c4ce/cluster/genesis/genesis/components/common.go#L237-L325),
expose no public-egress setting: each constructs the all-port public rule in
code. An additive NetworkPolicy cannot revoke an existing allow. A reviewed
upstream change or fork must rebuild and pin both generators, refresh the
expected-spec fixtures from their actual renders, and qualify required
destinations and private-range denial on the isolated canary before strict
enforcement.

The ten Octelium Enterprise Genesis policies have a separate [v0.22.0
expected-spec fixture](../clusters/homelab/apps/octelium-enterprise/generated-networkpolicies.json)
derived from the pinned [constructors](https://github.com/octelium/octelium-ee/tree/0e9368283420e17847879a58dc7f354b656ef3c3/cluster/genesis/genesis/components).
Their complete specs matched current live policies on October 20. Pass this
fixture as another `--render` input; it does not deploy or qualify their
ingress traffic. All 17 generated policies now have source-reviewed fixtures,
but Flannel still provides no NetworkPolicy enforcement and canary qualification
remains open.

The source policies now limit cloudflared's private egress to the two routed
Istio gateways and Octelium ingress dataplane, Harbor metrics ingress to the
Prometheus Pod, and Harbor/Mastodon gateway ingress to the Istio gateway Pod.
Mastodon's ambient namespace also allows gateway-origin HBONE on TCP/15008;
Istio [requires that destination port](https://github.com/istio/istio.io/blob/release-1.27/content/en/docs/ambient/usage/networkpolicy/index.md)
before traffic can reach its application ports.
Before enforcement, recheck live Service selectors, EndpointSlices and Pod labels,
then prove these paths on the isolated canary, including ambient HBONE and Service
translation and kubelet health probes. Mastodon's web and streaming Pods were
absent at source review, so their allowed path also needs a live canary proof.

Before making policies effective, finish owner/render review, publish every
fixture and controller image, admit a tainted node with measured memory and
local storage, and prove allowed and denied traffic plus restart, API-loss,
IP-reuse and reboot behavior on that node. Preserve DNS, API, mesh HBONE,
webhook, NFS and recovery access. A candidate fixture's narrow deny result
does not make the stock Enterprise agent's broad public TCP/443 egress a
domain allowlist. Follow the [canary and cleanup runbook](../clusters/homelab/platform/network-policy/README.md)
before expanding enforcement; deleting the DaemonSet alone may leave firewall
rules behind.

Nine [source-owned DNS policies](evidence/openclaw-enterprise-policy-review.json)
require CoreDNS Pods labeled `k8s-app=kube-dns` in `kube-system`; six were
narrowed in this review. Changing the `kube-dns` Service selector or CoreDNS
Pod labels requires updating all nine policies together, then proving TCP and
UDP 53 through the Service on the
isolated canary before firewall enforcement.
