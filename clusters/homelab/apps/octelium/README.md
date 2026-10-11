# Octelium Client Desired State

This app prepares a repo-owned Octelium client connector in the homelab.
Octelium is the replacement path for human app access. App hostnames keep their
existing `*.stinkyboi.com` names. Exact Cloudflare DNS records point those
names at the public Cloudflare Tunnel, and Octelium `WEB` Services proxy to the
existing Istio app routes. All app Services enforce browser login except
AFFiNE, which delegates login to the application for native-client support.

The deployed Kubernetes pieces are:

- `octelium-client` namespace with privileged Pod Security for the connector's
  `NET_ADMIN`/`MKNOD` TUN requirement and Istio ambient enrollment.
- `octelium-client-auth`, an ExternalSecret sourced from
  `/homelab/octelium/client-auth-token` and currently rendering the versioned
  target Secret `octelium-client-auth-v5`.
- The repo-owned `octelium-client` connector Deployment, configured for TUN
  mode with `NET_ADMIN` and `MKNOD`, explicitly enrolled in Istio ambient, and
  pinned to nodes labeled `octelium.com/node-mode-dataplane=` for future served
  workload upstreams. Istio CNI and ztunnel disable IPv6 to match the cluster's
  IPv4-only Pod/Service CIDRs and the connector's `--ip-mode=v4` setting.
  The pod resolves `octelium-api.stinkyboi.com` to the internal Istio gateway
  so the in-cluster connector does not depend on Cloudflare gRPC proxying.
- `octelium-demo`, a tiny in-cluster HTTP service that remains available as a
  harmless smoke-test target.
- `octelium-demo-allow-client`, a NetworkPolicy limiting demo ingress to the
  Octelium client pod and the generated Octelium WEB service proxy for the
  demo.

The Octelium resource catalog for the external Octelium Cluster is
`docs/examples/octelium/homelab-services.yaml`. It defines:

- Core `ClusterConfig` `default` with a 32-session human limit so stale CLI
  retries cannot exhaust the default 16-session allowance before expiry.
- Octelium Namespace `homelab` for apps and Namespace `ci` for CI-only
  transport.
- Policy `homelab-human-web-access`, which allows authenticated human client
  sessions and clientless browser sessions to app `WEB` Services.
- Policy `homelab-workload-web-serve`, reserved for the
  `homelab-octelium-client` workload User if a future Service needs a connector
  served upstream.
- Policy `homelab-private-kubernetes-access`, allowing the `homelab-owner`
  client full operator access and limiting `homelab-cordium-user` to
  Kubernetes `get`, `list`, and `watch` requests while denying Secrets,
  ConfigMaps, service accounts, authorization reviews, and sensitive
  subresources.
- Policy `homelab-ci-kubernetes-api-access`, allowing only the `homelab-ci`
  workload User to publish the Kubernetes API Service for CI.
- Workload User `homelab-octelium-client`, retained for connector bootstrap and
  future private upstreams.
- Workload User `homelab-ci` for GitHub Actions plan/apply and diagnostics.
- Human User `homelab-e2e` for noninteractive app-access validation.
- Private `KUBERNETES` Service `kubernetes-api.homelab`, forwarding to
  `https://10.1.0.199:6443` for operator and restricted read-only Cordium
  access, using the upstream kubeconfig CA for server verification.
- Clientless `KUBERNETES` Service `kubernetes-api-ci`, forwarding to
  `https://10.1.0.199:6443` for CI Kubernetes API access.
- Public `WEB` Services `affine`, `argocd`, `compass`, `deluge`, `dispatcharr`,
  `grafana`, `kiali`, `litellm`, `langfuse`, `n8n`, `nofx`, `octobot`, `openclaw`,
  `policy-bot`, `prowlarr`, `radarr`, and `sonarr`, whose public FQDNs are the
  existing app hostnames such as `https://grafana.stinkyboi.com`.
- `affine` is an anonymous Octelium app Service. AFFiNE signup is closed after
  bootstrap, and AFFiNE's own sessions protect workspace data while the public
  transport supports the native client's `assets://.` origin.
- `nofx` requires `homelab-human-web-access`; NOFX's own login remains a second
  authentication boundary.
- Cordium genesis owns the package-managed `default.cordium` public `WEB`
  Service with primary hostname `cordium`; the catalog attaches its narrow
  access policy to the dedicated `homelab-cordium-user` instead of declaring a
  duplicate `cordium` Service.
- WEB Service `homelab-demo.homelab` for service-proxy smoke tests.

The Enterprise console hostname `https://console.stinkyboi.com` is routed by
`octelium-public` to the Istio gateway and then by the `octelium-cluster`
`VirtualService` to the package-owned `console.octelium` backend. Do not model
it as a separate homelab catalog Service; the package canonical
`console.octelium.stinkyboi.com` hostname is nested and intentionally not
public.

Each app `WEB` Service forwards over HTTPS to the in-cluster Istio gateway
while setting the original app hostname in the HTTP headers. This internal
HTTPS hop avoids the gateway's HTTP-to-HTTPS redirect while preserving the
existing app `VirtualService` routes. Exact Cloudflare app records are proxied
CNAMEs to the public tunnel, so users can open the existing
`https://*.stinkyboi.com` URLs without running `octelium connect`.

The connector manifest runs at one replica after the Octelium Cluster API,
service catalog, and workload credential are verified. The `nodeSelector` keeps
the connector on Octelium dataplane nodes for smoke tests and future private
upstreams. Public app traffic does not depend on this connector; it enters
through `octelium-public`, reaches the Octelium ingress dataplane, and is
authorized as clientless `WEB` traffic except for AFFiNE's reviewed anonymous
transport.

## Activation And Cutover

Apply the external Octelium resources to the Octelium Cluster:

```sh
octeliumctl apply --include ClusterConfig docs/examples/octelium/homelab-services.yaml
octeliumctl apply docs/examples/octelium/homelab-services.yaml
```

The first command is separate because `--include ClusterConfig` replaces
`octeliumctl apply`'s normal resource-kind include list.

Configure Microsoft Entra as the portal login provider after
`IaC/live/azuread-applications/octelium` has applied:

```sh
scripts/octelium-entra-oidc.sh
```

To make an operator able to log in, pass a runtime-only user mapping. Keep the
actual contact email and Entra object ID out of git:

```sh
scripts/octelium-entra-oidc.sh \
  --admin-user-name homelab-owner \
  --admin-email '<contact-email>' \
  --admin-object-id '<entra-object-id>'
```

The script reads `/homelab/octelium/entra/*` from SSM, stores the generated
client secret in an Octelium native Secret, and applies IdentityProvider
`entra`. It binds login to immutable Entra `oid`; email is contact metadata.
Use `--dry-run` to preflight changes and follow the
[owner-conversion mapping checks](../../../../docs/octelium.md#entra-owner-conversion)
before upgrading an existing email-based mapping.

Create an authentication token credential for the workload user:

```sh
octeliumctl create cred \
  --user homelab-octelium-client \
  --policy homelab-workload-web-serve \
  homelab-octelium-client
```

Do not attach `homelab-human-web-access` to this workload credential. That
Policy is intentionally human-only and denies `WORKLOAD` users.

Store the printed token outside git:

```sh
aws ssm put-parameter \
  --region us-west-2 \
  --name /homelab/octelium/client-auth-token \
  --type SecureString \
  --overwrite \
  --value '<authentication-token>'
```

After the Octelium API is verified, store the credential in SSM, bump
`remoteRef.version` on `octelium-client-auth`, update the ExternalSecret target
Secret name to match that SSM version, and bump
`homelab.rst.io/octelium-credential-ssm-version` on both the ExternalSecret and
the connector pod annotations when the SSM version changes. Let Argo CD sync
`octelium`; the active connector then serves each configured Octelium Service
from inside the homelab cluster.

After the retained catalog is ready, use the
[staged private DNS cutover](../traefik/CUTOVER.md) for existing application and
control names. The old public DNS writer is removed. Keep legacy callbacks and
native routes only until their replacements pass authenticated acceptance.

`scripts/octelium-e2e-check.sh` describes the legacy public routing contract;
it is not a Traefik acceptance gate and can fail intentionally after DNS moves.
Use it only when diagnosing the retained pre-cutover path. The staged runbook
owns private canonical TLS, native API, callback and Cordium checks.

Use separate contexts when the Octelium control plane is not the homelab
cluster:

```sh
scripts/octelium-e2e-check.sh \
  --octelium-context <octelium-cluster-context> \
  --homelab-context <homelab-context>
```

Only publish app UI routes after this e2e gate passes.

## Bootstrap UI Access

Use `stinkyboi.com` as the Octelium Cluster domain. With this domain, clients
call `octelium-api.stinkyboi.com`, and the browser portal may use
`portal.stinkyboi.com`. `octelium.stinkyboi.com` remains a public alias, but it
is not the CLI domain because that would make clients call the nested
`octelium-api.octelium.stinkyboi.com` hostname that Cloudflare Universal SSL
does not cover.

Before DNS or VPN access reaches the Octelium Cluster ingress, bootstrap
through a local port-forward:

```sh
kubectl -n octelium get svc
sudo kubectl -n octelium port-forward svc/<octelium-ingress-service> 443:443
```

Add temporary host entries on the bootstrap workstation:

```text
127.0.0.1 octelium.stinkyboi.com
127.0.0.1 stinkyboi.com
127.0.0.1 portal.stinkyboi.com
127.0.0.1 octelium-api.stinkyboi.com
```

Then authenticate and apply the catalog while the port-forward is running:

```sh
octelium login --domain stinkyboi.com
scripts/octelium-entra-oidc.sh \
  --admin-user-name homelab-owner \
  --admin-email '<contact-email>' \
  --admin-object-id '<entra-object-id>'
octeliumctl apply --include ClusterConfig docs/examples/octelium/homelab-services.yaml
octeliumctl apply docs/examples/octelium/homelab-services.yaml
octeliumctl create cred \
  --user homelab-octelium-client \
  --policy homelab-workload-web-serve \
  homelab-octelium-client
```

Store the generated workload credential in SSM as shown above, sync the Argo CD
Application, and remove the temporary host entries after the VPN or real DNS
path works.

## Enterprise Package

Octelium Enterprise is tracked as the `octeliumee` package from
`https://github.com/octelium/octelium-ee`. The package installs into an
already running Octelium Cluster with `octops`; it is not synced by this Argo CD
Application and it does not replace the in-cluster client connector.

Current desired Enterprise package version:

```text
0.22.0
```

The Octelium Cluster domain is `stinkyboi.com`, so the client talks to
`octelium-api.stinkyboi.com`. Keep certificates valid for the apex plus
first-level `*.stinkyboi.com` names.

Install or upgrade it with the repo-owned wrapper:

```sh
scripts/octelium-enterprise-package.sh \
  --domain stinkyboi.com \
  --version 0.22.0

scripts/octelium-enterprise-package.sh \
  --domain stinkyboi.com \
  --version 0.22.0 \
  --upgrade
```

The operator host must have `octops` `v0.29.0` or later and kubeconfig access
to the Octelium Cluster. Keep any Enterprise license material outside git.

## Validation

Render before rollout:

```sh
kubectl kustomize clusters/homelab/apps/octelium
kubectl kustomize clusters/homelab/apps/istio
scripts/octelium-enterprise-package.sh --help
bash -n scripts/octelium-entra-oidc.sh
bash -n scripts/octelium-gateway-dns.sh scripts/tailscale-private-dns.sh
scripts/octelium-e2e-check.sh --help
```

After activation, inspect retained connector state; the e2e command below is legacy-only:

```sh
kubectl -n octelium-client get externalsecret,secret octelium-client-auth
kubectl -n octelium-client get deploy,pod -l app.kubernetes.io/instance=octelium-client
kubectl -n octelium-client logs deploy/octelium-client
scripts/octelium-gateway-dns.sh --dry-run
scripts/tailscale-private-dns.sh --dry-run
scripts/octelium-e2e-check.sh \
  --octelium-context <octelium-cluster-context> \
  --homelab-context <homelab-context>
```

Use the private Kubernetes Service from a dedicated operator client environment.
First configure the [local TCP carrier and scoped API resolver mapping](../octelium-public/README.md#routing).
Run these commands in that same container/network namespace. In-cluster
clients use the existing private API split DNS and do not need the public
carrier. Do not use a workstation-wide API hosts override, which would also
redirect browser gRPC-Web traffic:

```sh
octelium login --domain stinkyboi.com
octelium connect --domain stinkyboi.com --ip-mode=v4 -d
octelium config kubernetes-api.homelab --domain stinkyboi.com
```

Run the `KUBECONFIG` export printed by `octelium config`, set the generated file
to mode `0600`, then run `kubectl --request-timeout=15s get nodes`. A Cordium
Workspace already has a client session, so run the same `octelium config`,
`chmod`, and `kubectl` commands inside the Workspace. The server-side upstream
<!-- checkov:skip=CKV_SECRET_6:Public name of an Octelium Secret, not secret data. -->
kubeconfig stays in Octelium Secret `homelab-ci-kubeconfig`; neither Kubernetes
path needs Tailscale. Talos still uses the retained fallback transport.

Run `octelium disconnect --domain stinkyboi.com` after finishing the operator
session.

The app hostnames publish exact proxied Cloudflare Tunnel CNAME records, so
browser users can reach Octelium clientless `WEB` Services without a local VPN
session. Octelium CLI client sessions retain `octelium-api.stinkyboi.com` inside the
verified TLS stream carried through `octelium-transport.stinkyboi.com`, plus
the Gateway records. The smoke test below requires the same native transport
setup.

Use the smoke-test service when you want to validate the bridge separately from
app-specific auth:

```sh
octelium connect --domain stinkyboi.com -d \
  -p homelab-demo.homelab:18081
curl http://127.0.0.1:18081/version
octelium disconnect --domain stinkyboi.com
```

## Adding A Service

New application routes belong in [Traefik's fixed route inventory](../traefik/README.md)
and the guarded mesh DNS inventory. Keep canonical application hostnames private;
only the two reviewed callback hosts use Funnel. Do not add application hosts to
the retained Tunnel or recreate its deleted DNS writer.

Octelium's retained catalog serves Cordium and required control/Kubernetes
access. Changes to that catalog still require its reviewed reconciliation path
and preservation of Cordium identity and denied-resource boundaries.

## Rollback

Use reviewed GitOps reverts and the [ordered cutover rollback](../traefik/CUTOVER.md).
Preserve the connector, native credentials and carrier recovery until replacement
acceptance. A separate retirement change owns obsolete app routes; never bulk
delete the retained Cordium Kubernetes Service, policies or Enterprise state.
Tailscale/Traefik remains the target private application path, with public Funnel
limited to the reviewed n8n and Policy Bot callbacks.

Remove or downgrade the Enterprise package only through an Octelium-supported
package operation. Update the desired version and knowledge-base runbook before
running the wrapper again; preserve Enterprise PVCs and Cordium state.
