# Octelium Client Bridge

This repository prepares Octelium to replace Tailscale for human access to
homelab applications. Tailscale remains the temporary fallback for app routes
until the Octelium Cluster, service catalog, workload credential, connector, and
client tunnel all pass the e2e gate in `scripts/octelium-e2e-check.sh`.

The Tailscale operator can still have non-app responsibilities, such as CI
cluster reachability or reviewed public webhook exceptions, until those are
separately replaced. Do not remove the current tailnet app routes before the
Octelium e2e check passes.

## Current Model

The Argo CD Application at `IaC/live/argocd-apps/octelium` installs two source
types:

- The official Octelium client Helm chart from `ghcr.io/octelium/helm-charts`.
- Repo-owned Kubernetes support manifests from
  `clusters/homelab/apps/octelium`.

The Kubernetes namespace is `octelium-client`. It contains:

- `octelium-client-auth`, an ExternalSecret that reads
  `/homelab/octelium/client-auth-token` and renders the versioned workload
  token Secret consumed by the connector.
- `octelium-client`, the Helm-managed Octelium client Deployment running with
  `replicaCount: 1` after the Octelium API served real traffic and the catalog
  credential was stored in SSM.
- `octelium-demo`, a small Podinfo HTTP service exposed only as a ClusterIP.
- `octelium-demo-allow-client`, a NetworkPolicy that allows only the Octelium
  client pod to call the demo service once a policy-enforcing CNI exists.

The namespace is enrolled in Istio ambient mesh so protected apps can allow the
connector by service-account principal. The connector's principal is:

```text
cluster.local/ns/octelium-client/sa/octelium-client
```

The Octelium client is configured for `--implementation=gvisor`, so the
connector does not need `NET_ADMIN`, a TUN device, or privileged Pod Security.
That is slower than kernel WireGuard mode but is the safer default for this
cluster.

## Octelium Service Catalog

The external Octelium Cluster resources live at:

```text
docs/examples/octelium/homelab-services.yaml
```

They create:

- Octelium Namespace `homelab`.
- Policy `homelab-human-web-access`, allowing authenticated human client
  sessions to WEB Services in that namespace.
- Policy `homelab-workload-web-serve`, allowing only the
  `homelab-octelium-client` workload User to serve WEB Services in that
  namespace.
- Workload User `homelab-octelium-client`.
- WEB Services for the current homelab app routes:
  `argocd.homelab`, `compass.homelab`, `deluge.homelab`, `grafana.homelab`,
  `homelab-demo.homelab`, `kiali.homelab`, `litellm.homelab`, `n8n.homelab`,
  `octobot.homelab`, `openclaw.homelab`, `policy-bot.homelab`,
  `prowlarr.homelab`, `radarr.homelab`, and `sonarr.homelab`.

Each Service upstream points at the Kubernetes Service DNS name reachable from
inside this homelab cluster and is served by the workload user. The prepared
Kubernetes Deployment serves the same explicit list through `octelium.serve`,
and its workload credential is constrained with
`--scope=api:user.MainService/Connect` plus matching `--scope=service:<name>`
flags.

Apply the service catalog to the Octelium Cluster:

```sh
octeliumctl apply docs/examples/octelium/homelab-services.yaml
```

Create a workload authentication token:

```sh
octeliumctl create cred \
  --user homelab-octelium-client \
  --policy homelab-workload-web-serve \
  homelab-octelium-client
```

Do not attach `homelab-human-web-access` to this workload credential. That
Policy is intentionally human-only and denies `WORKLOAD` users.

Store the printed token in SSM, not git:

```sh
aws ssm put-parameter \
  --region us-west-2 \
  --name /homelab/octelium/client-auth-token \
  --type SecureString \
  --overwrite \
  --value '<authentication-token>'
```

## Human SSO

Microsoft Entra is the human login provider for the Octelium portal and CLI web
login flow. The Entra app registration is managed by
`IaC/live/azuread-applications/octelium`; it registers the
`https://octelium.stinkyboi.com/callback` and
`https://portal.octelium.stinkyboi.com/callback` redirect URIs and writes the
client ID, generated client secret, tenant ID, and issuer URL to
`/homelab/octelium/entra/*`.

After the Terragrunt unit applies, create the Octelium Secret and
IdentityProvider from the generated SSM values:

```sh
scripts/octelium-entra-idp.sh
```

The helper applies the `entra` IdentityProvider with
`identifierClaim: preferred_username`. Create or update HUMAN Users with an
explicit `identityProvider: entra` identity matching the Entra
`preferred_username` value for users that should log in.

## Cutover Gate

Run the e2e gate before removing any old Tailscale-backed app route:

```sh
scripts/octelium-e2e-check.sh
```

If the Octelium control plane is external to the homelab cluster, pass separate
Kubernetes contexts so control-plane checks run against the Octelium Cluster and
connector checks run against homelab:

```sh
scripts/octelium-e2e-check.sh \
  --octelium-context <octelium-cluster-context> \
  --homelab-context <homelab-context>
```

The gate verifies:

- the Octelium control-plane namespace and services exist;
- `octelium-client-auth` is synced from SSM and renders the versioned workload
  token Secret consumed by the connector;
- `octelium-client` has at least one ready replica;
- `octelium.stinkyboi.com`, `portal.octelium.stinkyboi.com`, and
  `octelium-api.octelium.stinkyboi.com` are not generic Istio `404` responses;
- every homelab WEB Service in `docs/examples/octelium/homelab-services.yaml`
  exists in the Octelium Cluster;
- a client tunnel can reach `homelab-demo.homelab`.

When it passes, remove the old application `VirtualService` objects that point
at `istio-system/tailnet-gateway`, remove the Tailscale-backed Istio
`LoadBalancer` path for app UI access, and keep only separately reviewed
non-app exceptions such as webhooks or CI cluster access. If it fails, treat the
failure output as the cutover work queue.

## Bootstrap UI Access

The Octelium Cluster domain for this homelab is `octelium.stinkyboi.com`.
With that domain, Octelium clients contact
`octelium-api.octelium.stinkyboi.com`, and browser access may also use
`portal.octelium.stinkyboi.com`. The existing Istio `*.stinkyboi.com`
certificate covers `octelium.stinkyboi.com`; it also requests
`*.octelium.stinkyboi.com` so the nested API and portal names can present a
valid certificate.

Until DNS or another private route reaches the Octelium Cluster ingress, use a
local port-forward as the bootstrap path:

```sh
kubectl -n octelium get svc
sudo kubectl -n octelium port-forward svc/<octelium-ingress-service> 443:443
```

For the bootstrap workstation only, point the Octelium Cluster names at the
local port-forward:

```text
127.0.0.1 octelium.stinkyboi.com
127.0.0.1 portal.octelium.stinkyboi.com
127.0.0.1 octelium-api.octelium.stinkyboi.com
```

Then authenticate and set up the cluster resources:

```sh
octelium login --domain octelium.stinkyboi.com
octeliumctl apply docs/examples/octelium/homelab-services.yaml
octeliumctl create cred \
  --user homelab-octelium-client \
  --policy homelab-workload-web-serve \
  homelab-octelium-client
```

Keep the port-forward and temporary host entries in place until the first VPN
or other private access path is working. Remove the temporary host entries once
real DNS can resolve the same names to the Octelium ingress.

Verify that the external Octelium API is actually serving before rotating the
workload credential or rolling the connector:

```sh
curl -vI https://octelium-api.octelium.stinkyboi.com
```

The TLS certificate must match `octelium-api.octelium.stinkyboi.com`, and the
endpoint must be the Octelium API rather than a generic Istio `404` or gRPC
`Unimplemented` response. Once that is true, create or rotate the
`homelab-octelium-client` credential, store it in SSM, bump
`remoteRef.version` on `octelium-client-auth`, update the ExternalSecret target
Secret name to match that SSM version, bump
`homelab.rst.io/octelium-credential-ssm-version` on both the ExternalSecret and
the connector pod annotations, sync the `octelium` Argo CD Application, then
run `scripts/octelium-e2e-check.sh`.

## Octelium Enterprise Package

Octelium Enterprise comes from
`https://github.com/octelium/octelium-ee` as the `octeliumee` Octelium package.
It is not a replacement for the Kubernetes client chart in this repository.
The package installs into an already running Octelium Cluster with `octops`,
while the homelab Kubernetes side remains the client connector and private
service bridge described above.

The current desired Enterprise package version for this homelab is `0.22.0`.
The upstream Enterprise README requires `octops` `v0.29.0` or later and an
existing Octelium Cluster. Commercial or production use requires an Enterprise
license; license material must stay outside git.

The configured Octelium Cluster domain is `octelium.stinkyboi.com`, which makes
the client use `octelium-api.octelium.stinkyboi.com`. The existing
`*.stinkyboi.com` wildcard covers the Cluster domain, and the certificate must
also cover `*.octelium.stinkyboi.com`; the one-level wildcard is not enough for
the API hostname.

Install the pinned package:

```sh
scripts/octelium-enterprise-package.sh \
  --domain octelium.stinkyboi.com \
  --version 0.22.0
```

Upgrade an existing Enterprise installation after this repository has been
updated to the intended package version:

```sh
scripts/octelium-enterprise-package.sh \
  --domain octelium.stinkyboi.com \
  --version 0.22.0 \
  --upgrade
```

Use `--kubeconfig <path>` when the Octelium Cluster kubeconfig is not the
default kubeconfig for the operator shell.

## Full Cluster Bootstrap

The self-hosted Octelium Cluster bootstrap is now represented by repo-owned
prerequisites plus the Octelium-native `octops init` operation.

Terragrunt/OpenTofu manages the Octelium node labels:

| Node | Octelium label |
| --- | --- |
| `zimaboard-0` | `octelium.com/node-mode-dataplane=` |
| `zimaboard-1` | `octelium.com/node-mode-controlplane=` |
| `zimaboard-2` | `octelium.com/node-mode-dataplane=` |

Argo CD manages:

- `platform-multus`, a Talos-compatible Multus thick DaemonSet in `kube-system`.
- `octelium-storage`, PostgreSQL and Redis stores in `octelium-storage`.
- `octelium-cluster`, the Istio `VirtualService` that routes
  `octelium.stinkyboi.com`, `portal.octelium.stinkyboi.com`, and
  `octelium-api.octelium.stinkyboi.com` to
  `octelium-ingress-dataplane.octelium.svc.cluster.local:8080`, plus the
  `DestinationRule` that upgrades Istio-to-Octelium upstream traffic to HTTP/2
  so Octelium CLI gRPC calls keep response trailers.

The `octelium-cluster` Application deliberately keeps the `VirtualService` in
`istio-system` and does not manage the `octelium` namespace. The Octelium
Cluster workloads and their runtime namespace are created and upgraded by
`octops`, and genesis deletes/recreates that namespace during `octops init`.
Automated pruning is disabled on the front-door Application so Argo does not
delete the formerly managed namespace during the handoff to `octops`.
Use the repo-owned wrapper after the prerequisite apps are synced:

```sh
scripts/octelium-cluster-bootstrap.sh \
  --domain octelium.stinkyboi.com \
  --version 0.35.0
```

The wrapper reads the generated storage credentials from
`octelium-storage-auth`, writes a temporary bootstrap file outside git, and runs
`octops init` with Octelium ingress front-proxy mode so the existing Istio
gateway terminates TLS. The wrapper sets `OCTELIUM_INGRESS_FRONT_PROXY=true`
for Octelium v0.35 and also sets the older `OCTELIUM_FRONT_PROXY_MODE=true`
name for documentation compatibility. The wrapper also labels the `octelium`
namespace with the privileged Pod Security profile that Octelium data-plane
workloads require. If an Octelium deployment already exists, the same wrapper
runs `octops upgrade`, answers the upgrade confirmation, and waits for the
newly created `octelium-genesis-upgrade-*` Job and Kubernetes workloads to roll
out instead of using Octelium's portal-authenticated wait mode.

After `octops` completes, apply the service catalog and create the connector
credential:

```sh
octeliumctl apply docs/examples/octelium/homelab-services.yaml
octeliumctl create cred \
  --user homelab-octelium-client \
  --policy homelab-workload-web-serve \
  homelab-octelium-client
```

Store the printed credential in `/homelab/octelium/client-auth-token`, then set
`replicaCount` to `1` in `clusters/homelab/apps/octelium/values.yaml`, sync the
`octelium` Argo CD Application, and run `scripts/octelium-e2e-check.sh`.

## Validation

Before rollout:

```sh
kubectl kustomize clusters/homelab/apps/octelium
kubectl kustomize clusters/homelab/apps/octelium-cluster
kubectl kustomize clusters/homelab/apps/octelium-storage
kubectl kustomize clusters/homelab/platform/multus
helm template octelium-client oci://ghcr.io/octelium/helm-charts/octelium \
  --version 0.3.0 \
  --namespace octelium-client \
  -f clusters/homelab/apps/octelium/values.yaml
scripts/octelium-cluster-bootstrap.sh --help
scripts/octelium-enterprise-package.sh --help
scripts/octelium-e2e-check.sh --help
```

After activation with `replicaCount: 1`:

```sh
kubectl -n octelium-client get externalsecret,secret octelium-client-auth
kubectl -n octelium-client get deploy,pod -l app.kubernetes.io/instance=octelium-client
kubectl -n octelium-client logs deploy/octelium-client
scripts/octelium-e2e-check.sh \
  --octelium-context <octelium-cluster-context> \
  --homelab-context <homelab-context>
```

Check the in-cluster demo locally:

```sh
kubectl -n octelium-client port-forward svc/octelium-demo 8080:8080
curl http://127.0.0.1:8080/version
```

Check a service through Octelium from a client machine:

```sh
octelium connect --domain octelium.stinkyboi.com -p grafana.homelab:18080
curl http://127.0.0.1:18080/api/health
```

## Rollback

Set `replicaCount` back to `0` and sync the `octelium` Argo CD Application.
That stops the connector while leaving Tailscale untouched.

If the external resources are no longer wanted, delete the homelab Services,
the `homelab-octelium-client` User, and the `homelab-human-web-access` Policy
from the Octelium Cluster with `octeliumctl`. Do not delete or change Tailscale
resources as part of Octelium rollback unless a later migration PR explicitly
replaces the tailnet ingress and exit-node model.

Remove or downgrade the Enterprise package through an Octelium-supported
package operation. Record the target package version in this document before
running the operator script again.
