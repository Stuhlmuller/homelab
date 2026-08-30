# Octelium

Tags: #runbook #octelium #access

Canonical runbook: [`docs/octelium.md`](../../octelium.md)

Octelium is the primary human-app, private Kubernetes, callback, and CI access
backbone. Operator machines run `octelium connect` and generate a kubeconfig
with `octelium config kubernetes-api.homelab`; Cordium Workspaces already have
their own client session and use the same private Service. Keep Cluster
bootstrap, Enterprise adoption, public Cloudflare routing, Entra OIDC, and the
end-to-end gate on their repository-owned scripts and manifests. The catalog
also owns the core human session ceiling; apply its `ClusterConfig` include
separately before the normal catalog apply.

Bootstrap and upgrade require the dataplane label on `zimaboard-0`, the
control-plane label on `zimaboard-1`, and no dataplane label on `zimaboard-2`.
The bootstrap script refuses to mutate the cluster if these selectors fail,
including a missing node or failed API lookup.

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

See [[../architecture/secrets-and-identity]], [[tailnet-ingress]], and
[[../workloads/inventory]].
