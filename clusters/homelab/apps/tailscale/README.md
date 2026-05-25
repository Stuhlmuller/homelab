# Tailscale Desired State

This path owns the repo-managed Tailscale operator support resources that are
applied alongside the upstream `tailscale-operator` Helm chart.

`namespace.yaml` owns the Pod Security labels for the `tailscale` namespace.
The operator-managed proxy Pods require privileged mode for kernel networking,
so this namespace intentionally uses privileged Pod Security enforcement while
the application Services remain reachable only through the tailnet.

## Runtime Secret

`externalsecret.yaml` creates the `operator-oauth` Kubernetes Secret from AWS
SSM Parameter Store. The Tailscale OAuth client must have the `Devices Core`,
`Auth Keys`, and `Services` write scopes and must use `tag:k8s-operator`.

## Pod Security

`namespace.yaml` labels the `tailscale` namespace for privileged Pod Security
admission. The upstream operator creates privileged proxy Pods for connector and
load-balancer devices so they can configure packet forwarding and Tailscale
networking. Without this label, the cluster's baseline Pod Security policy
rejects the operator-managed proxy Pods before they can start.

## Version

`IaC/live/argocd-apps/tailscale/terragrunt.hcl` pins the upstream
`tailscale-operator` Helm chart. Version `1.98.3` is the first rollout target
after the Tailscale admin console reported a known vulnerability on the older
operator-managed devices. If the upgrade regresses operator login, connector
readiness, or proxy Pod startup, roll back by reverting the chart
`target_revision` to `1.84.3` and syncing the Argo CD Application.

## Homelab Exit Node

`exit-node-connector.yaml` creates a cluster-scoped Tailscale `Connector` named
`homelab-exit-node`. The operator creates one proxy device with hostname
`homelab-exit-node`, tags it as `tag:k8s`, and advertises it as an exit node.

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
from the Machines page in the Tailscale admin console after Argo CD syncs this
app.

## Validation

Render desired state before applying:

```sh
kubectl kustomize clusters/homelab/apps/tailscale
```

After Argo CD syncs the `tailscale` Application:

```sh
kubectl get connector homelab-exit-node
kubectl wait connector homelab-exit-node --for=condition=ConnectorReady=true --timeout=5m
kubectl -n tailscale get statefulset,pod -l tailscale.com/parent-resource=homelab-exit-node
```

Expected result: the connector reports `ISEXITNODE` as `true`, the connector
condition is ready, and one operator-managed proxy Pod is running in the
`tailscale` namespace. Then select `homelab-exit-node` as the exit node from a
tailnet client and confirm the client egress IP changes to the homelab network.
