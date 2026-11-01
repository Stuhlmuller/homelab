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

Most existing non-privileged runtime namespaces use the `baseline` Pod Security
profile so new workloads cannot silently add privileged containers, host
networking, hostPath mounts, or other host-level access. The staged Enterprise
foundation declares `restricted` enforcement for `openclaw-system` and
`openclaw-agents`; neither namespace is active until its Application is synced.
Move a namespace to `privileged` only with the documented justification and
owner below. Baseline namespaces warn and audit against the stricter
`restricted` profile so future chart changes surface before becoming runtime
assumptions.

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

### Private ingress on the current worker (candidate, 2026-11-01)

Traefik is currently Ready on `zimaboard-1`; its operator-managed
`traefik-private` Tailscale proxy is a separate Pod on that node. A read-only
November 1 snapshot found 6,612 MiB requested against 7,282 MiB allocatable
and 6,189 MiB actual use. This is room for investigation, not a sidecar
capacity receipt: remeasure limits, image-pull space, peak use, and rollout
surge before changing placement.

The smaller private-listener design is a [userspace Tailscale sidecar](https://tailscale.com/docs/solutions/connect-kubernetes-pods-to-tailnet-using-sidecar)
in the same Traefik Pod. Bind only the private `web` and `websecure` entrypoints
to `127.0.0.1:8000` and `127.0.0.1:8443`; configure [raw TCP Serve](https://tailscale.com/docs/reference/tailscale-cli/serve#use-a-tcp-forwarder)
for tailnet ports 80 and 443 to those loopback ports. Traefik must still
terminate HTTPS with its existing certificate. Keep the separate Funnel and
registry listeners and their exact routes. A Pod-IP or ClusterIP caller cannot
reach another Pod's loopback listener, so this boundary could survive a
kube-router crash or cold start without relocating Traefik or draining
`zimaboard-0`. It is a proposed architecture, not an enforced boundary yet.

Stage it in reviewed source before cutting over:

1. Stage a second one-replica Traefik controller on `zimaboard-1` with distinct
   labels, route ConfigMap, and Tailscale sidecar. Prove no existing private,
   Funnel, or registry Service selector matches the new Pod; keep the current
   controller and operator LoadBalancer intact. Use a distinct tailnet hostname,
   pinned images, bounded resources, durable per-Pod Tailscale state, narrow Secret
   RBAC, and a repository-owned authentication contract. Gate deployment on
   measured two-controller capacity. Keep Tailnet Lock enabled and extend the
   fixed signer to verify and sign only that exact identity. Prove raw TCP,
   original TLS certificate, HTTPS, native gRPC, ACLs, and both containers'
   readiness on the test peer. A Tailscale health response proves an IP, not a
   signed peer or the intended Serve configuration; check both explicitly.
2. Prove denied direct private routes from ordinary Pods on the same and a
   different node, from a host, and through Pod IP on ports 80, 8000, 443,
   and 8443, ClusterIP on ports 80 and 443, and the sidecar's `100.64.0.0/10`
   address. Repeat while Tailscale is absent, restarting, unsigned, or unable
   to pull its image.
   Repeat after Traefik replacement, Pod-IP reuse, and node reboot. Prove
   allowed tailnet clients and the independent registry/Funnel paths. Set a
   no-surge rollout or prove measured two-Pod capacity before the live switch.
3. Replace the current DNS and internal-client contracts in source. The
   [`tailnet-dns` resolver](../clusters/homelab/platform/tailnet-dns/README.md)
   now publishes the `traefik-private` LoadBalancer status IP; its checker and
   [signer](../scripts/tailscale-ingress-sign.py) assume an operator proxy.
   A candidate is a selectorless headless Service with
   [`k8s-gateway.dns/resolve-endpoints: "true"`](https://github.com/k8s-gateway/k8s_gateway#endpoint-resolution)
   and one repo-owned, ready EndpointSlice containing the sidecar's persistent
   tailnet IP. The pinned resolver can answer from ready endpoints, but a
   static slice would leave stale DNS after identity loss. Keep the new
   EndpointSlice unready until cutover. Add an owner that
   binds the IP to the exact online, signed node key and withdraws readiness
   when that identity is lost; prove DNS becomes unavailable rather than
   answering a stale or reassigned IP. Validate this with the real pinned
   resolver and checker before private DNS can move. The
   [CoreDNS rewrites](../clusters/homelab/platform/dns/coredns-configmap.yaml)
   for `harbor.stinkyboi.com` and `octelium-api.stinkyboi.com` currently target
   that Service; preserve it until both reviewed internal replacements and
   Harbor node pulls and native Octelium clients pass.
4. Validate the new peer and DNS from a trusted tailnet client, then change
   the declared private DNS path while the old controller still serves. Create
   a separate internal Service for the accepted Harbor/API callers, then
   retire the old operator LoadBalancer through GitOps after acceptance.
   [Kubernetes does not permit changing a set `loadBalancerClass`](https://kubernetes.io/docs/concepts/services-networking/service/#specifying-class-of-load-balancer-implementation),
   so do not try to convert that Service in place. Keep a reviewed rollback to
   its previous Service and DNS declarations until the new path survives
   restart and client acceptance.
   Retire the 18 old Octelium/Istio app routes and broad app gateway only after
   each caller passes on the new path. Preserve named native Octelium control
   paths and separately reviewed callbacks. Require
   `scripts/ci/legacy-ingress-retirement-check.py --retired` and negative
   in-cluster bypass probes. The current [audit](../scripts/ci/legacy-ingress-retirement-check.py)
   reports 54 legacy source entries.

This route addresses the private Traefik listener only. It does not enforce
general `NetworkPolicy`, narrow the generated broad egress rules, or prove
existing app backends inaccessible through other Services. Do not claim the
private-ingress finding closed until the sidecar, DNS, old-route retirement,
and live negative probes all pass. The isolated worker route below remains
the separate candidate for general `NetworkPolicy` qualification.

### NetworkPolicy canary on an existing node (2026-11-01)

No spare worker is available. A read-only snapshot found `zimaboard-2` using
1,339 MiB against 1,308 MiB allocatable, before the staged 576 MiB
enforcer/client limit budget and 128 MiB reserve. It cannot pass admission.
Closed [#1584](https://github.com/Stuhlmuller/homelab/pull/1584) proposed moving
only `zimaboard-2` workloads to `acer`/`zimaboard-1`; closed
[#1583](https://github.com/Stuhlmuller/homelab/pull/1583) proposed restarting
Langfuse PostgreSQL on `acer`. Neither changed live state. Do not incur that
database outage solely to clear `zimaboard-2`. Any later database move still
requires a fresh verified off-NAS checkpoint.

`zimaboard-0` is a conditional candidate, not an admitted canary. It has
7,282 MiB allocatable, 5,852 MiB used, and 8.1 GiB node filesystem free.
One enforcer, client, Traefik Pod, and 128 MiB reserve consume 1,216 MiB at
their limits, leaving only 214 MiB at this snapshot. Traefik's current
one-Pod surge raises that budget to 1,728 MiB, 298 MiB beyond free memory.
The node also hosts 64 active app Pods, including 55 Octelium Pods, plus 19
completed backup Pods and the `kube-system/image-rewrite` Deployment Pod.
[Canary admission](../scripts/network-policy-canary-node.py) rejects all 84
foreign assigned Pods, even completed ones or Pods in `kube-system`. Deluge,
Radarr, Sonarr, and Bazarr have config volumes pinned to local `hostPath` PVs;
Prometheus uses an NFS claim. The active app Pods request about 3,733 MiB,
while `acer` and `zimaboard-1` together have about 3,052 MiB unrequested.
A taint leaves existing Pods in place. Source-owned relocation or an explicitly
planned service outage, storage recovery proof, and fresh capacity/Pod
inventories are prerequisites to isolating this worker.

A candidate existing-node maintenance route requires these source-owned stages
and fresh capacity and recovery checks. The November 1 read-only check found
no required reviewer on `homelab-plan`; restore it before any credentialed
Terragrunt plan or apply in this route.

1. Verify current media config archives and the media PostgreSQL recovery path.
   Through GitOps, pause Prometheus and Deluge, Radarr, Sonarr, and Bazarr;
   preserve their PVCs and local PVs. Suspend the four media backup CronJobs
   and disable Bazarr's z0-pinned PostSync backup/reconcile Jobs for the outage.
   This pauses monitoring and four media apps, without moving their local
   data. Their current requests total about 2,512 MiB, enough to close the
   681 MiB destination request deficit at this snapshot.
2. Set `successfulJobsHistoryLimit: 0` in the Bazarr, Deluge, Radarr, Sonarr,
   Harbor, Octelium storage, and Fleet `backup-cronjob.yaml` sources. Verify
   the controllers remove all 19 retained successful Jobs and Pods. Keep
   Fleet, Harbor, and Octelium backups running. If reconciliation does not
   remove them, add a reviewed, identity-bounded cleanup script; never delete
   them by hand.
3. Move Prowlarr's committed node selector to `acer`. Add Octelium dataplane
   eligibility to `acer` through the node-label Terragrunt owner, update its
   gateway override, and prove native/Multus endpoints and destination capacity
   before removing `zimaboard-0` eligibility. The 55 Octelium Pods and client
   use that label; existing Pods remain until eviction.
4. Apply a temporary `NoExecute` taint to `zimaboard-0` through the repo-owned
   node-label Terragrunt unit. Expect an Octelium/private-app interruption as
   its gateway and 54 other Pods move together. Confirm `image-rewrite` moves
   off the node and its webhook stays healthy. Require all displaced workloads
   Ready and native gateway and client paths working after rescheduling.
   Verify every Pod except the reviewed system DaemonSet Pods has left,
   including completed Jobs.
   Obtain a fresh, exact-UID placement receipt and run protected canary
   admission. Remove the temporary taint only after the dedicated canary
   `NoSchedule` taint is installed, and recheck the Pod list.

No stage above authorizes the firewall or Traefik. A shared-node Traefik move
needs a guard that installs default-drop on its Pod interface before the
container starts, survives kube-router loss, and ties openings to exact Pod
identity so IP reuse cannot inherit access. A CNI attachment hook with an
independent policy controller is a candidate, not implemented here. Talos
[host ingress rules](https://docs.siderolabs.com/talos/v1.14/networking/ingress-firewall)
do not supply this Pod boundary, and kube-router starts its full policy sync
asynchronously. Prove cold boot, image-cache miss, enforcer crash/restart,
policy deletion, Pod replacement/IP reuse, and same-node, cross-node, and
host-origin bypass negatives before placement. If any gate fails, leave
Traefik on its current node and restore paused workloads through reviewed
GitOps/Terragrunt changes, then verify local PV startup and backup schedules.

Only after an existing worker is empty of unrelated Pods, retarget and validate
the canary source, then run the protected baseline, admission, fixture-first
pull, enforcement, and traffic gates. Before placing Traefik there, prove a
persistent fail-closed boundary through cold boot, image-cache miss, and
enforcer stop/restart: [kube-router v2.11.1](https://github.com/cloudnativelabs/kube-router/blob/v2.11.1/pkg/controllers/netpol/npc_iptables.go)
can report healthy before async policy sync and clear its tail chain during
restart. Use `surge: 0` and
`unavailable: 1` for any single-node Traefik move, with a documented ingress
outage. The legacy Istio/Octelium ClusterIP bypass must be retired after
caller acceptance and negative probes. Keep enforcement disabled if any
capacity, identity, policy, lifecycle, or bypass gate fails.

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
