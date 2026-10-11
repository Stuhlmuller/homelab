# Tailscale Desired State

This path owns the repo-managed Tailscale operator support resources that are
applied alongside the upstream `tailscale-operator` Helm chart.

`namespace.yaml` owns the Pod Security labels for the `tailscale` namespace.
The operator-managed exit-node Connector proxy requires privileged mode for
kernel networking, so this namespace intentionally uses privileged Pod Security
enforcement. The operator also exposes the private Traefik LoadBalancer, two
path-limited Funnel proxies, and an authenticated Kubernetes API proxy. See the
[ordered ingress cutover](../traefik/CUTOVER.md) before moving DNS or CI.

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

`IaC/stacks/tailscale/stack.hcl` pins the upstream `tailscale-operator` Helm chart at
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

Keep this Connector for remote Talos/LAN access. Application traffic moves to
private Traefik and CI moves to the operator API proxy in separate cutover
phases. Cordium retains its restricted native Octelium Kubernetes Service.

The complete reviewed policy and pre-signed CI auth keys are managed through
the [Tailscale provider unit](../../../../IaC/modules/tailscale-access/README.md).
That unit owns operator tag permissions and automatic exit-node/subnet-route
approvals. Apply reviewed source through its saved-plan workflow; do not edit
policy or approve devices manually to bypass a failed deployment.

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

Expected result: the operator and exit-node proxy run `v1.102.3`, the proxy
StatefulSet has matching current and update revisions, the connector reports
`ISEXITNODE` as `true`, its condition is ready, the advertised route includes
`10.1.0.0/24`, and the Istio Service remains `ClusterIP` with no Tailscale
address. Then select `homelab-exit-node` on a client and verify DNS, HTTPS
egress, and access to a LAN address in `10.1.0.0/24`.

## Internal image contract

`values.yaml` pins both `operatorConfig.image` and `proxyConfig.image` to
Harbor copies of the reviewed 1.102.3 digests. The latter becomes `PROXY_IMAGE`
in the rendered operator and controls generated Connector/Service proxy Pods.
A ProxyClass can override it; review any new ProxyClass image and kube-apiserver
ProxyGroup image separately. Neither resource existed in the read-only audit
on 2026-10-10. Changing the proxy reference recreates singleton proxies; retain
the current digest and verify tailnet and node registry paths before rollout.
