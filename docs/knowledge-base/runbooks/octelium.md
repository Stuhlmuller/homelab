# Octelium

Tags: #runbook #octelium #access

Canonical runbook: [`docs/octelium.md`](../../octelium.md)

Octelium is the primary human-app, callback, and CI access backbone. Keep
Cluster bootstrap, Enterprise adoption, public Cloudflare routing, Entra OIDC,
and the end-to-end gate on their repository-owned scripts and manifests. The
catalog also owns the core human session ceiling; apply its `ClusterConfig`
include separately before the normal catalog apply.

The public CLI edge uses the host-networked `octelium-api-upnp` CronJob on
`zimaboard-0` to renew WAN TCP/8443 to `10.1.0.200:30443`. The job cannot enable
Xfinity UPnP, so router authority remains a rollout gate. Grafana alerts before
the 24-hour lease expires, and the end-to-end check pins its gRPC request to a
public DNS answer instead of trusting local split DNS.

The temporary August 2026 recovery manifest runs the control paths, CI API,
and 18 additional public WEB Service fallbacks on `acer` without Multus, 19
including the existing OctoBot fallback. Its generated Service UIDs must be
refreshed after any Service recreation. Keep it until the native fleet passes
the capacity, 24-hour stability, direct Pod, and public end-to-end removal
gates in [[../architecture/cluster-topology]].

Prometheus owns runtime alerts that Argo cannot derive from captured resources:
committed role-node capacity, stale terminating Pods labeled
`octelium.com/component=svc`, public HTTP/2 gRPC, and the unauthenticated NOFX
denial contract. Homelab Overview lists active unready and stale terminating
proxy Pods plus unavailable Octelium Deployments, while the generic Deployment
alert remains the replica-availability owner. Start with the read-only checks
in the canonical runbook; recovery requires full role capacity, fresh success
for both monitoring CronJobs, no degraded proxy row, and the complete e2e gate.
The deliberate live failure/recovery exercise remains blocked until an approved
maintenance window can interrupt the primary access plane safely.

See [[../architecture/secrets-and-identity]], [[tailnet-ingress]], and
[[../workloads/inventory]].
