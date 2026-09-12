# Tailscale Desired State

This path owns the repo-managed Tailscale operator support resources that are
applied alongside the upstream `tailscale-operator` Helm chart.

`namespace.yaml` owns the Pod Security labels for the `tailscale` namespace.
The operator-managed exit-node Connector proxy requires privileged mode for
kernel networking, so this namespace intentionally uses privileged Pod Security
enforcement. Tailscale does not expose application Services; Octelium owns human
app access. Helm disables the Tailscale IngressClass and API-server proxy.

## Runtime Secret

`externalsecret.yaml` creates the `operator-oauth` Kubernetes Secret from AWS
SSM Parameter Store. The Tailscale OAuth client must have the `Devices Core`,
`Auth Keys`, and `Services` write scopes and must use `tag:k8s-operator`.

## Pod Security

`namespace.yaml` labels the `tailscale` namespace for privileged Pod Security
admission. The upstream operator creates a privileged proxy Pod for the
exit-node Connector so it can configure packet forwarding and Tailscale
networking. Without this label, the cluster's baseline Pod Security policy
rejects the operator-managed proxy Pod before it can start.

## Version

`IaC/terragrunt.stack.hcl` pins the upstream `tailscale-operator` Helm chart at
`1.102.3`. The chart updates both the operator and its managed proxy image and
includes Tailscale security fix TS-2026-011. The exit-node proxy rollout briefly
interrupts VPN egress. If the upgrade regresses operator login, connector
readiness, or proxy startup, revert the chart to `1.98.3` and sync the Argo CD
Application.

## Homelab Exit Node

`exit-node-connector.yaml` creates a cluster-scoped Tailscale `Connector` named
`homelab-exit-node`. The operator creates one proxy device with hostname
`homelab-exit-node`, tags it as `tag:k8s`, and advertises it only as an exit
node. It does not advertise a subnet route, expose applications, or proxy the
Kubernetes API.

Keep this Connector for outbound VPN egress. Remote app, Kubernetes, and Talos
API access use Octelium. Undeclared LAN appliances remain local-only until an
explicit Octelium Service and policy are reviewed.

Tailnet policy must allow the operator tag to own `tag:k8s`:

```json
"tagOwners": {
  "tag:k8s-operator": [],
  "tag:k8s": ["tag:k8s-operator"]
}
```

To avoid manual approval after every recreation, auto-approve exit-node
advertisement for `tag:k8s` in the Tailscale policy:

```json
"autoApprovers": {
  "exitNode": ["tag:k8s"]
}
```

If auto-approval is not configured, approve `homelab-exit-node` as an exit node
from the Machines page after Argo CD syncs this app. Remove any obsolete
`10.1.0.0/24` route auto-approval from tailnet policy.

## Validation

Render desired state before applying:

```sh
kubectl kustomize clusters/homelab/apps/tailscale
```

After Argo CD syncs the `tailscale` Application:

```sh
kubectl get connector homelab-exit-node
kubectl wait connector homelab-exit-node --for=condition=ConnectorReady=true --timeout=5m
kubectl -n tailscale get deployment,statefulset,pod
kubectl -n istio-system get service istio-ingressgateway
kubectl get ingressclass tailscale --ignore-not-found -o name
```

Expected result: the operator and exit-node proxy run `v1.102.3`, the proxy
StatefulSet has matching current and update revisions, the connector reports
`ISEXITNODE` as `true`, its condition is ready, `SUBNETROUTES` is empty, the
Tailscale IngressClass is absent, and the Istio Service remains `ClusterIP`
with no Tailscale address. Then select `homelab-exit-node` on a client, verify
DNS and HTTPS egress. From an off-LAN client with no other subnet advertiser
or direct route, confirm access to `10.1.0.0/24` fails.
