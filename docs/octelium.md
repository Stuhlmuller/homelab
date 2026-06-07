# Octelium Client Bridge

This repository uses Octelium for human access to homelab applications. App
hostnames keep their existing `*.stinkyboi.com` names, exact DNS points those
names at Octelium private service IPs, and per-app Istio `VirtualService`
objects provide only the backend SNI routing layer for Octelium TCP/443
Services.

CI cluster reachability now uses the Octelium `kubernetes-api.homelab` Service.
Keep only separately reviewed non-app exceptions, such as public webhook
ingress, on their existing paths until they are replaced in their own changes.

## Current Model

The Argo CD Application at `IaC/live/argocd-apps/octelium` installs the
repo-owned Kubernetes manifests from `clusters/homelab/apps/octelium`.

The Kubernetes namespace is `octelium-client`. It contains:

- `octelium-client-auth`, an ExternalSecret that reads
  `/homelab/octelium/client-auth-token` and renders the versioned workload
  token Secret consumed by the connector.
- `octelium-client`, the repo-owned Octelium client Deployment running after
  the Octelium API served real traffic and the catalog credential was stored in
  SSM. It resolves `octelium-api.stinkyboi.com` to the internal Istio gateway
  to avoid depending on Cloudflare gRPC proxying for the in-cluster connector.
- `octelium-demo`, a small Podinfo HTTP service exposed only as a ClusterIP.
- `octelium-demo-allow-client`, a NetworkPolicy that allows only the Octelium
  client pod to call the demo service once a policy-enforcing CNI exists.

The namespace is enrolled in Istio ambient mesh so protected apps can allow the
connector by service-account principal. The connector's principal is:

```text
cluster.local/ns/octelium-client/sa/octelium-client
```

The Octelium client is configured for `--implementation=tun` with `NET_ADMIN`
and `MKNOD` so it can create `/dev/net/tun` when a workload connector is needed.
The current app access path does not hairpin through that connector: generated
Octelium service pods forward directly to the in-cluster Istio gateway. The
connector is pinned to nodes with `octelium.com/node-mode-dataplane=` for any
future served workload upstreams. The `octelium-client` namespace is therefore a
narrow privileged namespace; it does not host the Octelium data plane.

## Octelium Service Catalog

The external Octelium Cluster resources live at:

```text
docs/examples/octelium/homelab-services.yaml
```

They create:

- Octelium Namespace `homelab`.
- Policy `homelab-human-web-access`, allowing authenticated human client
  sessions to app Services in those namespaces.
- Policy `homelab-workload-web-serve`, reserved for the
  `homelab-octelium-client` workload User if future Services need connector
  served upstreams.
- Policy `homelab-ci-kubernetes-api-access`, allowing only the
  `homelab-ci` workload User to access the Kubernetes API Service.
- Workload User `homelab-octelium-client`, retained for connector bootstrap and
  future private upstreams.
- Workload User `homelab-ci` for GitHub Actions plan/apply and diagnostics.
- Human User `homelab-e2e` for noninteractive app-access validation.
- TCP/6443 Service `kubernetes-api.homelab`, forwarding to
  `tcp://10.1.0.199:6443` for CI Kubernetes API access.
- TCP/443 Services for the current homelab app routes. The Octelium service
  names remain valid internal names such as `grafana.homelab`, and each service
  carries an `appHostname` attribute such as `grafana.stinkyboi.com`.
- WEB Service `homelab-demo.homelab` for service-proxy smoke tests.

Each app Service forwards TCP/443 to the in-cluster Istio gateway so the
existing HTTPS hostname, SNI routing, and wildcard certificate remain the app
contract. Exact Cloudflare records then point those app hostnames at Octelium
private service IPs, which makes the browser path VPN-only without changing app
base URLs. Do not set `spec.config.upstream.user` on these app Services unless
the route intentionally needs a served workload connector; keeping the upstream
direct avoids an unnecessary connector-session hop.

Apply the service catalog to the Octelium Cluster:

```sh
octeliumctl apply --domain stinkyboi.com docs/examples/octelium/homelab-services.yaml
```

## Microsoft Entra Login

The Octelium portal login provider is Microsoft Entra OIDC. The Entra
application registration is managed by:

```text
IaC/live/azuread-applications/octelium
```

The application uses `https://stinkyboi.com/callback` as the primary OAuth
redirect URI. `https://portal.stinkyboi.com/callback` is also
registered because browser sessions may start from the portal hostname. The
unit writes the generated client ID, one-year client secret, tenant ID, and
tenant-specific issuer URL to SSM under `/homelab/octelium/entra/*`.

After that Terragrunt unit has applied, configure the Octelium native
IdentityProvider from the SSM values:

```sh
scripts/octelium-entra-oidc.sh
```

For an operator/admin login, apply a runtime-only HUMAN user mapping. Do not
commit personal email addresses or Entra identifiers into this public repo:

```sh
scripts/octelium-entra-oidc.sh \
  --admin-user-name homelab-owner \
  --admin-email '<entra-user-principal-name>'
```

The script reads the generated SSM parameters, creates or updates the Octelium
native Secret `entra-oidc-client-secret`, applies IdentityProvider `entra`, and,
when both admin flags are supplied, applies a HUMAN user with an explicit Entra
identity and the built-in `allow-all` policy. The IdentityProvider requests the
`openid`, `email`, and `profile` OIDC scopes, and Octelium uses the Entra
`preferred_username` claim as the login identifier. Microsoft Entra may omit
`email_verified`, so the IdentityProvider intentionally does not require that
claim.

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

## Cutover Gate

Run the e2e gate before declaring any Octelium app route ready:

```sh
scripts/octelium-e2e-check.sh
```

For noninteractive tunnel validation, provide a client authentication token.
The gate starts an Octelium client session and curls the existing
`https://*.stinkyboi.com` app hostnames. It fails if any app hostname still
resolves to the old Tailscale wildcard instead of an Octelium private service
IP. The operator-side e2e client publishes each app Service to a loopback port
and uses the real `*.stinkyboi.com` URL and SNI with `curl --connect-to`, so it
does not depend on root-only route installation on the operator workstation.
Use a HUMAN credential, such as one created for `homelab-e2e` with
`homelab-human-web-access`, not the workload credential used by the in-cluster
connector.

```sh
OCTELIUM_AUTH_TOKEN='<authentication-token>' scripts/octelium-e2e-check.sh
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
- `stinkyboi.com`, `portal.stinkyboi.com`, `octelium-api.stinkyboi.com`, and
  the `octelium.stinkyboi.com` alias respond over TLS. The API host may
  return `404` at the HTTP root because the real API is gRPC;
- every homelab app Service in `docs/examples/octelium/homelab-services.yaml`
  exists in the Octelium Cluster;
- IdentityProvider `entra` exists in the Octelium Cluster;
- each existing app hostname resolves to an Octelium private service IP and
  responds over HTTPS through the VPN.

Keep per-app `VirtualService` objects as private Istio backend routes for the
Octelium TCP Services. CI cluster access now uses the
`kubernetes-api.homelab` Octelium Service; keep only separately reviewed
Tailscale-specific non-app exceptions such as webhooks. If the gate fails,
treat the failure output as the repair work queue.

## Bootstrap UI Access

The Octelium Cluster domain for this homelab is `stinkyboi.com`. With that
domain, Octelium clients contact `octelium-api.stinkyboi.com`, and browser
access may use `portal.stinkyboi.com`. `octelium.stinkyboi.com` is kept as a
public Octelium alias, but it is not the CLI domain because
`octelium-api.octelium.stinkyboi.com` would require paid nested wildcard
coverage at Cloudflare. The Istio origin certificate requests `stinkyboi.com`
plus `*.stinkyboi.com`, which covers the domain, API, portal, and alias names.

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
127.0.0.1 stinkyboi.com
127.0.0.1 portal.stinkyboi.com
127.0.0.1 octelium-api.stinkyboi.com
```

Then authenticate and set up the cluster resources:

```sh
octelium login --domain stinkyboi.com
scripts/octelium-entra-oidc.sh \
  --admin-user-name homelab-owner \
  --admin-email '<entra-user-principal-name>'
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
curl -vI https://octelium-api.stinkyboi.com
```

The TLS certificate must match `octelium-api.stinkyboi.com`, and the
endpoint must be the Octelium API rather than a generic Istio `404` or gRPC
`Unimplemented` response. The CLI and VPN path also requires Cloudflare to
allow gRPC for the zone:

```sh
scripts/octelium-cloudflare-grpc.sh --dry-run
scripts/octelium-cloudflare-grpc.sh
```

This reads `/homelab/octelium/cloudflare-zone-settings-token`, which must be a
Cloudflare API token with `Zone:Read` and `Zone Settings:Edit` for
`stinkyboi.com`. The cert-manager DNS-01 token cannot update this setting.

Once the API and gRPC path are true, create or rotate the
`homelab-octelium-client` credential, store it in SSM, bump
`remoteRef.version` on `octelium-client-auth`, update the ExternalSecret target
Secret name to match that SSM version, bump
`homelab.rst.io/octelium-credential-ssm-version` on both the ExternalSecret and
the connector pod annotations, sync the `octelium` Argo CD Application, then
run `scripts/octelium-e2e-check.sh`.

After the Octelium Gateways report public addresses, reconcile exact Cloudflare
DNS records for their `_gw-*` hostnames:

```sh
scripts/octelium-gateway-dns.sh --dry-run
scripts/octelium-gateway-dns.sh
scripts/octelium-app-dns.sh --dry-run
scripts/octelium-app-dns.sh
```

The gateway reconciler prevents `_gw-*` names from falling through to the
tailnet wildcard record. The app reconciler creates exact `AAAA` records such
as `grafana.stinkyboi.com -> fdee:b76e:...` from Octelium Service status, so
app traffic uses the VPN without overlapping Tailscale IPv4 routes.

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

The configured Octelium Cluster domain is `stinkyboi.com`, which makes the
client use `octelium-api.stinkyboi.com`. The Istio and Cloudflare edge
certificates only need apex plus first-level `*.stinkyboi.com` coverage.

Install the pinned package:

```sh
scripts/octelium-enterprise-package.sh \
  --domain stinkyboi.com \
  --version 0.22.0
```

Upgrade an existing Enterprise installation after this repository has been
updated to the intended package version:

```sh
scripts/octelium-enterprise-package.sh \
  --domain stinkyboi.com \
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
  `stinkyboi.com`, `octelium.stinkyboi.com`, `portal.stinkyboi.com`, and
  `octelium-api.stinkyboi.com` to
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
  --domain stinkyboi.com \
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

Then reconcile the public gateway DNS records:

```sh
scripts/octelium-gateway-dns.sh --dry-run
scripts/octelium-gateway-dns.sh
scripts/octelium-app-dns.sh --dry-run
scripts/octelium-app-dns.sh
```

After `octops` completes, apply the service catalog and create the connector
credential:

```sh
octeliumctl apply docs/examples/octelium/homelab-services.yaml
octeliumctl create cred \
  --user homelab-octelium-client \
  --policy homelab-workload-web-serve \
  homelab-octelium-client
```

Store the printed credential in `/homelab/octelium/client-auth-token`, sync the
`octelium` Argo CD Application, and run `scripts/octelium-e2e-check.sh`.

## Validation

Before rollout:

```sh
kubectl kustomize clusters/homelab/apps/octelium
kubectl kustomize clusters/homelab/apps/octelium-cluster
kubectl kustomize clusters/homelab/apps/octelium-storage
kubectl kustomize clusters/homelab/platform/multus
bash -n scripts/octelium-gateway-dns.sh
bash -n scripts/octelium-app-dns.sh
bash -n scripts/octelium-entra-oidc.sh
bash -n scripts/octelium-cloudflare-grpc.sh
scripts/octelium-cluster-bootstrap.sh --help
scripts/octelium-enterprise-package.sh --help
scripts/octelium-e2e-check.sh --help
```

After activation:

```sh
kubectl -n octelium-client get externalsecret,secret octelium-client-auth
kubectl -n octelium-client get deploy,pod -l app.kubernetes.io/instance=octelium-client
kubectl -n octelium-client logs deploy/octelium-client
scripts/octelium-cloudflare-grpc.sh --dry-run
scripts/octelium-gateway-dns.sh --dry-run
scripts/octelium-app-dns.sh --dry-run
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
octelium connect --domain stinkyboi.com --ip-mode=both
curl -I https://grafana.stinkyboi.com/
```

The app hostnames publish exact `AAAA` records that point at Octelium private
IPv6 service addresses, so a human client session must use `--ip-mode=both` or
IPv6. `--ip-mode=v4` is reserved for the CI Kubernetes API publish path below
and will not route `grafana.stinkyboi.com`, `argocd.stinkyboi.com`, or the
other browser app hostnames.

Cloudflare Tunnel public hostname routes can serve the Octelium portal, but
Cloudflare currently documents gRPC over Tunnel as supported through private
subnet routing rather than public hostname deployments. If
`scripts/octelium-e2e-check.sh` reports Cloudflare HTTP `403` for the
`octelium-api.stinkyboi.com` gRPC probe, outside-tailnet Octelium CLI sessions
will not be reliable until the API is published through a gRPC-capable route.

Check the CI Kubernetes API service through Octelium from a client machine:

```sh
octelium connect \
  --domain stinkyboi.com \
  --implementation gvisor \
  --ip-mode=v4 \
  --no-dns \
  --publish kubernetes-api.homelab:127.0.0.1:16443
curl -kfsS https://127.0.0.1:16443/version
```

The `homelab-ci-kubernetes-api-access` policy is the enforcement boundary for
this workload credential. Do not add Octelium `--scope` flags to this CI
connection on v0.35; scoped auth-token sessions are denied before the
Kubernetes API listener is published.

## Rollback

Set the connector Deployment replicas to `0` and sync the `octelium` Argo CD
Application. That stops the connector while leaving Tailscale untouched.

If the external resources are no longer wanted, delete the homelab Services,
the `homelab-octelium-client` User, the `homelab-ci` User, and the
homelab Policies
from the Octelium Cluster with `octeliumctl`. Do not delete or change Tailscale
resources as part of Octelium rollback unless a later migration PR explicitly
replaces the remaining webhook and LAN tailnet model.

Remove or downgrade the Enterprise package through an Octelium-supported
package operation. Record the target package version in this document before
running the operator script again.
