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

### Replace an invalid operator OAuth client

Use `scripts/tailscale-operator-oauth-rotate.py` after this source reaches a clean,
current `main` checkout. The one-shot command follows the
[pinned Tailscale provider's keys API call](https://github.com/tailscale/terraform-provider-tailscale/blob/v0.29.2/tailscale/resource_oauth_client.go#L137-L163)
to mint a client with exactly `devices:core`, `auth_keys`, `services` and
`tag:k8s-operator`. Its authority is a separately supplied Owner/Admin Tailscale
API key in a regular 0600 file inside a 0700 directory outside the repository;
the existing limited Terragrunt OAuth client cannot authorize this replacement. Choose an
existing named AWS profile authorized to read and write the two declared SSM SecureStrings. Place the
private receipt in an existing 0700 directory outside the repository. Never
pass a key value as an argument or paste it into a log.

```sh
python3 scripts/tailscale-operator-oauth-rotate.py preflight \
  --api-key-file /private/path/tailscale-owner-api-key \
  --receipt /private/0700-directory/operator-oauth-receipt.json \
  --aws-profile YOUR_SSM_AUTHORIZED_PROFILE
python3 scripts/tailscale-operator-oauth-rotate.py rotate \
  --api-key-file /private/path/tailscale-owner-api-key \
  --receipt /private/0700-directory/operator-oauth-receipt.json \
  --aws-profile YOUR_SSM_AUTHORIZED_PROFILE
```

`preflight` only reads: it checks the current main revision, local Secret and
tag policy contracts, both SSM parameter types and values, and API-key access.
It does not prove the key can mint the required client; the actual create call
does. `rotate` writes a 0600 receipt before that call, verifies the new client
can request all three scopes and the operator tag, writes the client secret
then ID to the existing SSM slots, and reads both back without printing them.
The receipt contains the new credentials: keep it private, retain it through
rollout, and remove it through the approved secret-retirement process. On a
partial SSM failure, rerun with the same receipt; it will not mint another
client. If it remains in `creating`, the API response was not durably captured.
Stop: identify the request ID's client using a read-only key inventory, then
add a reviewed repo-owned cleanup path before retrying. Do not delete or
recreate a Tailscale client through the portal.

SSM writes alone do not update `operator-oauth`: this ExternalSecret uses
`refreshPolicy: OnChange`. After both values pass readback, merge a small GitOps
PR that adds or changes a public rotation-ID annotation on this
`ExternalSecret`'s `metadata`. Wait for `tailscale-oauth` Ready and a new target
Secret resource version. Then merge a separate PR changing
`operatorConfig.podAnnotations` in `values.yaml` to the same rotation ID. The
pinned chart mounts `operator-oauth` as files and uses that value to roll the
`operator` Deployment. Check `kubectl -n tailscale rollout status deployment/operator
--timeout=5m`, the operator's authentication, the Connector condition, and the
private ingress and API proxy. Keep the old OAuth client until those checks
pass. If rollout fails, leave the previous client in place and prepare a
reviewed repo-owned recovery using the prior SSM versions and the same two
GitOps revisions. This helper does not implement rollback; an SSM version
change alone is inert under `OnChange`.

The separate `tag:homelab-ingress-canary` in the staged ingress canary is not
granted to this OAuth client. Before activation, a reviewed tailnet policy
change must make `tag:k8s-operator` an owner of that canary tag. A read-only
OAuth token request with the new client can prove the `auth_keys` scope and
operator tag, but actual canary auth-key creation is a later write test.

## Pod Security

`namespace.yaml` labels the `tailscale` namespace for privileged Pod Security
admission. The upstream operator creates a privileged proxy Pod for the
exit-node Connector so it can configure packet forwarding and Tailscale
networking. Without this label, the cluster's baseline Pod Security policy
rejects the operator-managed proxy Pod before it can start.

## Version

`IaC/homelab/us-west-2/apps/tailscale/stack.hcl` pins the upstream `tailscale-operator` Helm chart at
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
the [Tailscale provider unit](../../../../IaC/terragrunt-catalog/modules/tailscale-access/README.md).
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
