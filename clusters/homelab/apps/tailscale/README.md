# Tailscale Desired State

This path owns the repo-managed Tailscale operator support resources that are
applied alongside the upstream `tailscale-operator` Helm chart.

`namespace.yaml` owns the Pod Security labels for the `tailscale` namespace.
The operator-managed exit-node Connector proxy requires privileged mode for
kernel networking, so this namespace intentionally uses privileged Pod Security
enforcement. Tailscale does not expose application Services; Octelium owns human
app access.

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
includes Tailscale security fix TS-2026-011. The two singleton proxies roll
separately, briefly interrupting the exit-node and Istio tailnet paths. If the
upgrade regresses operator login, connector readiness, or proxy startup,
revert the chart to `1.98.3` and sync the Argo CD Application.

## Homelab Exit Node

`exit-node-connector.yaml` creates a cluster-scoped Tailscale `Connector` named
`homelab-exit-node`. The operator creates one proxy device with hostname
`homelab-exit-node`, tags it as `tag:k8s`, advertises it as an exit node, and
advertises the homelab LAN route `10.1.0.0/24`.

Tailnet policy must allow the operator tag to own `tag:k8s`:

```json
"tagOwners": {
  "tag:k8s-operator": [],
  "tag:k8s": ["tag:k8s-operator"]
}
```

To avoid manual approval after every recreation, auto-approve exit-node and
subnet-route advertisement for `tag:k8s` in the Tailscale policy:

```json
"autoApprovers": {
  "exitNode": ["tag:k8s"],
  "routes": {
    "10.1.0.0/24": ["tag:k8s"]
  }
}
```

If auto-approval is not configured, approve `homelab-exit-node` as an exit node
and approve the `10.1.0.0/24` route from the Machines page in the Tailscale
admin console after Argo CD syncs this app.

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
```

Expected result: the operator and both managed proxy Pods run `v1.102.3`, both
StatefulSets have matching current and update revisions, the connector reports
`ISEXITNODE` as `true`, its condition is ready, the advertised route includes
`10.1.0.0/24`, and the Istio Service retains its Tailscale address. Then select
`homelab-exit-node` on a client and verify DNS, HTTPS egress, and access to a
LAN address in `10.1.0.0/24`.
