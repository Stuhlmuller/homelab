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

`IaC/terragrunt.stack.hcl` pins the upstream `tailscale-operator` Helm chart at
`1.102.3`. This release updates the operator and its managed proxy image,
recreating the exit-node Pod and replacing a failed PeerAPI DNS listener. It
also includes Tailscale security fix TS-2026-011. If the rollout regresses
operator login, connector readiness, or proxy Pod startup, revert the change
and sync the Argo CD Application; the prior `1.98.3` release restores service
but lacks that security fix.

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
kubectl -n tailscale get statefulset,pod -l tailscale.com/parent-resource=homelab-exit-node
```

Expected result: the connector reports `ISEXITNODE` as `true`, the connector
condition is ready, the advertised route includes `10.1.0.0/24`, and one
operator-managed proxy Pod is running in the `tailscale` namespace. Then select
`homelab-exit-node` as the exit node from a tailnet client and confirm the
client egress IP changes to the homelab network while local homelab LAN
addresses remain reachable.

If connecting through the exit node removes internet access while the client
still reports connected, inspect client logs for a timed-out PeerAPI resolver
such as `http://<exit-node-tailnet-ip>:<port>/dns-query`. Reconcile this app to
apply the pinned operator/proxy upgrade and roll the managed proxy Pod, then
reconnect the client and repeat the egress and DNS checks above.
