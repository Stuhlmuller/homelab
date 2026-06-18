# Octelium Client Bridge

This repository uses Octelium for human access to homelab applications. App
hostnames keep their existing `*.stinkyboi.com` names. Exact Cloudflare DNS
records point those names at the public Cloudflare Tunnel, the tunnel forwards
them to the Octelium public ingress, and Octelium `WEB` Services enforce login
before proxying to the existing Istio app routes.

CI cluster reachability now uses the Octelium `kubernetes-api.ci` Service.
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
and `MKNOD` so it can create `/dev/net/tun` for the demo and any future
connector-served upstream. The production app access path does not require a
local user VPN session or the in-cluster connector: public app requests enter
through Cloudflare Tunnel, land on the Octelium public ingress, and are
authorized as clientless browser sessions before Octelium forwards them to the
in-cluster Istio gateway.

## Octelium Service Catalog

The external Octelium Cluster resources live at:

```text
docs/examples/octelium/homelab-services.yaml
```

They create:

- Octelium Namespace `homelab` for the demo and Namespace `ci` for CI-only
  transport.
- Policy `homelab-human-web-access`, allowing authenticated human client
  sessions and clientless browser sessions to app `WEB` Services.
- Policy `homelab-cordium-user-access`, allowing only the dedicated
  `homelab-cordium-user` HUMAN identity to reach the public Cordium `WEB`
  Service.
- Policy `homelab-workload-web-serve`, reserved for the
  `homelab-octelium-client` workload User if future Services need connector
  served upstreams.
- Policy `homelab-ci-kubernetes-api-access`, allowing only the
  `homelab-ci` workload User to create an Octelium client session and access
  the Kubernetes API Service.
- Workload User `homelab-octelium-client`, retained for connector bootstrap and
  future private upstreams.
- Workload User `homelab-ci` for GitHub Actions plan/apply and diagnostics.
- Human User `homelab-e2e` for noninteractive app-access validation.
- TCP/6443 Service `kubernetes-api.ci`, forwarding to
  `tcp://10.1.0.199:6443` for CI Kubernetes API access.
- Public `WEB` Services `argocd`, `compass`, `cordium`, `deluge`, `grafana`,
  `kiali`, `litellm`, `n8n`, `octobot`, `openclaw`, `policy-bot`, `prowlarr`,
  `radarr`, and `sonarr`. Their public FQDNs are the existing app hostnames,
  such as `https://grafana.stinkyboi.com`.
- Cordium-specific identities: HUMAN User `homelab-cordium-user` for browser
  workspace access and WORKLOAD User `homelab-cordium-agent` for agent API
  automation through `cordium-agent-api.homelab`, plus the matching
  `cordium-users` and `cordium-agents` Groups those Users reference.
- WEB Service `homelab-demo.homelab` for service-proxy smoke tests.

The Enterprise console hostname `https://console.stinkyboi.com` is not an
Octelium app catalog Service. The public tunnel forwards it to the Istio
gateway, and the `octelium-cluster` `VirtualService` routes it to the
package-owned `console.octelium` backend without exposing the nested
`console.octelium.stinkyboi.com` hostname.

Each app `WEB` Service forwards HTTPS to the in-cluster Istio gateway while
setting `Host`, `X-Forwarded-Host`, `X-Forwarded-Port`, and
`X-Forwarded-Proto` for the original app hostname. The HTTPS hop avoids the
gateway's HTTP-to-HTTPS redirect loop for authenticated clientless browser
requests. The header block also sets `forwardedMode: TRANSPARENT` so Octelium
preserves those explicit forwarded headers instead of deriving them from the
internal upstream. That keeps each app's existing Istio `VirtualService` and
base URL intact while moving the user-facing authentication layer to Octelium
clientless access.

Apply the service catalog to the Octelium Cluster:

```sh
octeliumctl apply --domain stinkyboi.com docs/examples/octelium/homelab-services.yaml
```

Cordium is bootstrapped by the `cordium` Argo CD Application after that catalog
exists. The app runs upstream `cordium-genesis init` from a pinned
`ghcr.io/octelium/cordium-genesis:0.12.7` image and routes the public
`https://cordium.stinkyboi.com` browser path plus workspace app subdomains under
`*.cordium.stinkyboi.com` through the Octelium `cordium` WEB Service. Browser
access is scoped to the dedicated `homelab-cordium-user` HUMAN identity
through `homelab-cordium-user-access`. Agent automation should use a credential
for `homelab-cordium-agent` scoped to `homelab-cordium-agent-api-access`; do
not reuse the human browser identity for automated workspace runs. Workspace
defaults stay with upstream Cordium until this repository adds a reviewed
Cordium-native workspace configuration resource.

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

The gate uses ordinary public HTTPS requests to the existing
`https://*.stinkyboi.com` app hostnames. It fails if any app hostname still
resolves to Octelium private service IPs, if an app Service is not `WEB` with
`isPublic: true`, or if the public hostname returns a routing 404.

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
- every homelab app Service in `docs/examples/octelium/homelab-services.yaml`,
  including `cordium` and `cordium-agent-api.homelab`,
  exists in the Octelium Cluster;
- IdentityProvider `entra` exists in the Octelium Cluster;
- each existing app hostname resolves publicly through Cloudflare and responds
  over HTTPS without `octelium connect`; the Enterprise console check must not
  redirect to `console.octelium.stinkyboi.com`.

Keep per-app `VirtualService` objects as private Istio backend routes for the
Octelium `WEB` Services. CI cluster access now uses the `kubernetes-api.ci`
Octelium Service; keep only separately reviewed Tailscale-specific non-app
exceptions such as webhooks. If the gate fails, treat the failure output as the
repair work queue.

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
`Unimplemented` response. The public CLI and VPN path also needs Cloudflare to
accept gRPC and keep the long-lived `MainService/Connect` stream open. A
healthy unauthenticated gRPC-shaped probe returns HTTP/2 with
`content-type: application/grpc` and `grpc-status: 16`, not a Cloudflare HTTP
`403`:

```sh
curl -sS \
  --http2 \
  -H 'content-type: application/grpc' \
  -H 'te: trailers' \
  --data-binary '' \
  -o /dev/null \
  -D - \
  https://octelium-api.stinkyboi.com/octelium.api.main.user.v1.MainService/GetStatus
```

The tunnel transport is pinned to QUIC in `octelium-public`; if
`kubectl -n istio-system logs deploy/istio-ingressgateway` shows
`POST /octelium.api.main.user.v1.MainService/Connect` ending with
`DR http2.remote_reset` after roughly 125 seconds, treat that as a tunnel
transport regression rather than an Octelium login failure. Keep UDP/7844
allowed to public IPv4 destinations in the `cloudflared-egress` NetworkPolicy
while QUIC is enabled. Keep private and link-local IPv4 ranges excluded and DNS
scoped to cluster DNS.

The CLI and VPN path also requires Cloudflare to allow gRPC for the zone:

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
DNS records for their `_gw-*` hostnames when gateway hostnames are needed, then
publish the control-plane and app hostnames through the public Cloudflare
Tunnel:

```sh
scripts/octelium-gateway-dns.sh --dry-run
scripts/octelium-gateway-dns.sh
scripts/octelium-public-dns.sh --dry-run
scripts/octelium-public-dns.sh
```

The gateway reconciler prevents `_gw-*` names from falling through to stale
wildcard records. The public DNS reconciler creates exact proxied CNAME records
for `stinkyboi.com`, Octelium API/portal aliases, `console.stinkyboi.com`, and
the app hostnames such as `grafana.stinkyboi.com`, all pointing at the named
Cloudflare Tunnel target.

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

Live homelab state: `octeliumee` `0.22.0` was installed on 2026-06-10 UTC with
`scripts/octelium-enterprise-package.sh`. The package creates `octeliumee-*`
Deployments plus Octelium Services such as `console.octelium`,
`enterprise.octelium-api`, `public.octelium`, and `dirsync.octelium`. It also
provisions `octelium-rscstore`, `octelium-logstore`, and
`octelium-metricstore` PVCs on `nfs-default`; preserve or back up those PVCs
before removing or reinstalling the Enterprise package.

The Kubernetes steady state for those Enterprise resources is now committed in
`clusters/homelab/apps/octelium-enterprise` and registered by
`IaC/live/argocd-apps/octelium-enterprise`. The Argo CD Application adopts the
package Deployments, Services, ConfigMaps, ServiceAccounts, and PVC
declarations after the initial `octops` package install. Generated Secrets such
as `sys-init-kek`, database credentials, license material, and kubeconfigs stay
outside git.

The `octeliumee-logstore`, `octeliumee-metricstore`, and
`octeliumee-rscstore` Deployments use `Recreate` because each store opens a
DuckDB-backed `store.db` on its PVC. Do not change those workloads back to
rolling updates unless the package moves to a multi-writer-safe storage model.
Keep resource-level `argocd.argoproj.io/sync-options: Replace=true` on those
Deployments so Argo uses replace semantics for the strategy handoff and clears
the package-adopted rolling-update field. Omit `rollingUpdate`; an explicit
`rollingUpdate: null` can compare differently from the live object's absent
field.

The generated Enterprise service-proxy Deployments `svc-console-octelium`,
`svc-dirsync-octelium`, `svc-enterprise-octelium-api`, and
`svc-public-octelium` keep digest-pinned images in the committed package
capture, but the Octelium controller normalizes live `vigil` and `managed`
container images back to tag-only references. The `octelium-enterprise` Argo CD
Application ignores exactly those image fields with
`RespectIgnoreDifferences=true` so automated self-heal does not fight the
controller-owned values.

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

After install or upgrade, refresh the GitOps capture in
`clusters/homelab/apps/octelium-enterprise/resources.yaml`, keep images pinned
as `tag@sha256:digest`, preserve `Recreate` and resource-level `Replace=true`
on the three store Deployments, omit `rollingUpdate`, preserve the generated
service-proxy image ignore rule, and sync the `octelium-enterprise` Argo CD
Application.

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
  `octelium-ingress-dataplane.octelium.svc.cluster.local:8080`, routes
  `console.stinkyboi.com` to `svc-console-octelium`, plus the `DestinationRule`
  that upgrades Istio-to-Octelium upstream traffic to HTTP/2 so Octelium CLI
  gRPC calls keep response trailers.

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
`octelium-storage-auth`, writes a temporary bootstrap file outside git, enables
`network.quicv0.enable` for hosted CI tunnels, and runs `octops init` with
Octelium ingress front-proxy mode so the existing Istio gateway terminates TLS.
The wrapper sets `OCTELIUM_INGRESS_FRONT_PROXY=true` for Octelium v0.35 and also
sets the older `OCTELIUM_FRONT_PROXY_MODE=true` name for documentation
compatibility. The wrapper also labels the `octelium` namespace with the
privileged Pod Security profile that Octelium data-plane workloads require. If
an Octelium deployment already exists, the same wrapper reads the full current
`ClusterConfig` with `octeliumctl`, sets only
`spec.network.quicv0.enable=true`, applies the full updated config back to the
Cluster, runs `octops upgrade`, answers the upgrade confirmation, and waits for
the newly created `octelium-genesis-upgrade-*` Job and Kubernetes workloads to
roll out instead of using Octelium's portal-authenticated wait mode. Existing
Cluster upgrades therefore require `octeliumctl`, `jq`, and an Octelium admin
login in addition to the Kubernetes access used by `octops`.

Then reconcile public DNS:

```sh
scripts/octelium-gateway-dns.sh --dry-run
scripts/octelium-gateway-dns.sh
scripts/octelium-public-dns.sh --dry-run
scripts/octelium-public-dns.sh
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

Cordium genesis `0.12.7` declares the non-root image user by name
(`octelium`). Kubelet cannot verify that named user when `runAsNonRoot` is set,
so the hook pins the image's numeric runtime identity (`runAsUser: 100`,
`runAsGroup: 65533`). Bump
`homelab.rst.io/cordium-genesis-revision` when the hook template needs to be
recreated.

## Validation

Before rollout:

```sh
kubectl kustomize clusters/homelab/apps/octelium
kubectl kustomize clusters/homelab/apps/octelium-cluster
kubectl kustomize clusters/homelab/apps/octelium-storage
kubectl kustomize clusters/homelab/platform/multus
bash -n scripts/octelium-gateway-dns.sh
bash -n scripts/octelium-app-dns.sh
bash -n scripts/octelium-public-dns.sh
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
scripts/octelium-public-dns.sh --dry-run
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
octelium connect --domain stinkyboi.com --ip-mode=v4
curl -I https://grafana.stinkyboi.com/
```

The app hostnames publish exact `A` and `AAAA` records that point at the shared
Octelium private app gateway, so a human client session can use `--ip-mode=v4`,
`--ip-mode=v6`, or `--ip-mode=both` depending on the client network.

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
  --publish kubernetes-api.ci:127.0.0.1:16443
curl -kfsS https://127.0.0.1:16443/version
```

The `homelab-ci-kubernetes-api-access` policy is the enforcement boundary for
this workload credential. Do not add Octelium `--scope` flags to this CI
connection on v0.35; scoped auth-token sessions are denied before the
Kubernetes API listener is published.
The CI helper defaults to a per-GitHub-run Octelium homedir. Keep that behavior
on self-hosted runners so a stale local OcteliumDB refresh token cannot bypass a
freshly rotated `OCTELIUM_CI_AUTH_TOKEN`. CI also runs `octelium connect` with
logout-on-exit and the `if: always()` disconnect helper calls both
`octelium disconnect` and `octelium logout` against the same ephemeral homedir
so auth-token sessions do not accumulate. The self-hosted runner maps
`octelium-api.stinkyboi.com` to the Istio ingress gateway ClusterIP with
`OCTELIUM_API_HOST_ALIAS`; keep that alias on CI paths because the public
Cloudflare hostname can answer unauthenticated gRPC probes while authenticated
CLI success responses still lose required trailers. CI keeps `--no-dns` enabled
because it only needs the localhost `kubernetes-api.ci` publish and later Nix
or Kubernetes commands should keep the runner's normal DNS resolver. The
credential helper verifies GitHub environment secret write access with a
temporary write/delete, refreshes an existing Credential's User and Policy
binding, and refuses existing-credential rotation when GitHub secret updates are
disabled. If the `homelab-ci` user hits the Octelium server-side active-session
cap, use the credential helper's
`--delete-user-sessions-only` mode to clear only those workload sessions before
rerunning CI.

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
