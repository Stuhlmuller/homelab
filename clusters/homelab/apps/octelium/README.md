# Octelium Client Desired State

This app prepares a repo-owned Octelium client connector in the homelab.
Octelium is the replacement path for human app access. App hostnames keep their
existing `*.stinkyboi.com` names, exact DNS points those names at Octelium
private service IPs, and per-app Istio `VirtualService` objects provide only the
backend SNI routing layer for Octelium TCP/443 Services.

The deployed Kubernetes pieces are:

- `octelium-client` namespace with privileged Pod Security for the connector's
  `NET_ADMIN`/`MKNOD` TUN requirement and Istio ambient enrollment.
- `octelium-client-auth`, an ExternalSecret sourced from
  `/homelab/octelium/client-auth-token` and currently rendering the versioned
  target Secret `octelium-client-auth-v5`.
- The repo-owned `octelium-client` connector Deployment, configured for TUN
  mode with `NET_ADMIN` and `MKNOD`, and pinned to nodes labeled
  `octelium.com/node-mode-dataplane=` for future served workload upstreams.
  The pod resolves `octelium-api.stinkyboi.com` to the internal Istio gateway
  so the in-cluster connector does not depend on Cloudflare gRPC proxying.
- `octelium-demo`, a tiny in-cluster HTTP service that remains available as a
  harmless smoke-test target.
- `octelium-demo-allow-client`, a NetworkPolicy limiting demo ingress to the
  Octelium client pod and the generated Octelium WEB service proxy for the
  demo.

The Octelium resource catalog for the external Octelium Cluster is
`docs/examples/octelium/homelab-services.yaml`. It defines:

- Octelium Namespace `homelab`.
- Policy `homelab-human-web-access`, which allows authenticated human client
  sessions to app Services in those namespaces.
- Policy `homelab-workload-web-serve`, reserved for the
  `homelab-octelium-client` workload User if a future Service needs a connector
  served upstream.
- Policy `homelab-ci-kubernetes-api-access`, allowing only the `homelab-ci`
  workload User to publish the Kubernetes API Service for CI.
- Workload User `homelab-octelium-client`, retained for connector bootstrap and
  future private upstreams.
- Workload User `homelab-ci` for GitHub Actions plan/apply and diagnostics.
- Human User `homelab-e2e` for noninteractive app-access validation.
- TCP/6443 Service `kubernetes-api.homelab`, forwarding to
  `tcp://10.1.0.199:6443` for CI Kubernetes API access.
- TCP/443 Service `homelab-app-gateway.homelab`, the shared authenticated
  Octelium app gateway for existing `*.stinkyboi.com` hostnames.
- TCP/443 Services for the existing HTTPS app routes. The Octelium service
  names remain valid internal names such as `grafana.homelab`, and each service
  carries an `appHostname` attribute such as `grafana.stinkyboi.com` so DNS
  automation knows which hostnames belong to the shared app gateway.
- WEB Service `homelab-demo.homelab` for service-proxy smoke tests.

The shared app gateway forwards TCP/443 to the in-cluster Istio gateway so the
existing `https://*.stinkyboi.com` URLs, SNI routing, and wildcard certificate
continue to work. Exact Cloudflare app records point those hostnames at the same
Octelium private app-gateway A and AAAA addresses, so clients reach them through
the VPN instead of the old Tailscale wildcard.

The connector manifest runs at one replica after the Octelium Cluster API,
service catalog, and workload credential are verified. The `nodeSelector` keeps
the connector on Octelium dataplane nodes. The prepared
`--scope=api:user.MainService/Connect` and
`--scope=service:<name>` entries keep the workload credential constrained to
the User API stream, the shared app gateway, and the same app service names
while the connector is active.

## Activation And Cutover

Apply the external Octelium resources to the Octelium Cluster:

```sh
octeliumctl apply docs/examples/octelium/homelab-services.yaml
```

Configure Microsoft Entra as the portal login provider after
`IaC/live/azuread-applications/octelium` has applied:

```sh
scripts/octelium-entra-oidc.sh
```

To make an operator able to log in, pass a runtime-only user mapping. Keep the
actual Entra user principal name out of git:

```sh
scripts/octelium-entra-oidc.sh \
  --admin-user-name homelab-owner \
  --admin-email '<entra-user-principal-name>'
```

The script reads `/homelab/octelium/entra/*` from SSM, stores the generated
client secret in an Octelium native Secret, and applies IdentityProvider
`entra`.

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

After the service catalog is applied and the connector has reconnected,
reconcile DNS:

```sh
scripts/octelium-gateway-dns.sh
scripts/octelium-app-dns.sh
```

Then run:

```sh
scripts/octelium-e2e-check.sh
```

For noninteractive tunnel validation, provide a client authentication token.
The gate starts an Octelium client session and curls the existing
`https://*.stinkyboi.com` app hostnames. It fails if any hostname still
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
  --admin-email '<entra-user-principal-name>'
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
scripts/octelium-enterprise-package.sh --help
bash -n scripts/octelium-entra-oidc.sh
bash -n scripts/octelium-cloudflare-grpc.sh
bash -n scripts/octelium-app-dns.sh scripts/octelium-gateway-dns.sh
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

From an Octelium client session, query one of the existing app URLs:

```sh
octelium connect --domain stinkyboi.com --ip-mode=v4
curl -I https://grafana.stinkyboi.com/
```

The app hostnames publish exact `A` and `AAAA` records that point at the shared
Octelium private app gateway, so IPv4-only client sessions can browse the
existing `*.stinkyboi.com` app hostnames.

Use the smoke-test service when you want to validate the bridge separately from
app-specific auth:

```sh
octelium connect --domain stinkyboi.com -p homelab-demo.homelab:18081
curl http://127.0.0.1:18081/version
```

## Adding A Service

1. Add the Octelium `Service` to
   `docs/examples/octelium/homelab-services.yaml`.
2. For app UI routes, use a valid internal Octelium service name in the
   `homelab` namespace, set `spec.attrs.appHostname` to the existing
   `*.stinkyboi.com` hostname, and forward TCP/443 to
   `tcp://istio-ingressgateway.istio-system.svc.cluster.local:443`.
3. Add the service name to both the connector `--serve` list and the matching
   `--scope=service:<name>` entry in `connector.yaml`. Keep
   `--scope=api:user.MainService/Connect` present so the scoped token can open
   the User API connection stream.
4. Run `scripts/octelium-app-dns.sh --dry-run` after
   `homelab-app-gateway.homelab` reports an Octelium private address. The exact
   app hostname must point at the shared gateway address, not the per-app
   service address.
5. If the destination workload has an Istio `AuthorizationPolicy`, add
   `cluster.local/ns/octelium-client/sa/octelium-client` as an allowed source.
6. If the destination workload has a Kubernetes `NetworkPolicy`, add the
   `octelium-client` namespace as an ingress source. This is currently intent
   only while kube-flannel is the CNI.
7. Re-render the Octelium app and the changed destination app.

## Rollback

Set the connector Deployment replicas to `0` and sync the Argo CD Application.
That stops the connector without touching Tailscale.

To remove the external Octelium resources:

```sh
for service in \
  argocd.homelab compass.homelab deluge.homelab grafana.homelab \
  homelab-demo.homelab kiali.homelab litellm.homelab n8n.homelab \
  octobot.homelab openclaw.homelab policy-bot.homelab \
  prowlarr.homelab radarr.homelab sonarr.homelab; do
  octeliumctl delete svc "${service}"
done

octeliumctl delete user homelab-octelium-client
octeliumctl delete policy homelab-human-web-access
```

Do not delete or change Tailscale resources as part of Octelium rollback unless
a later migration PR explicitly replaces the tailnet ingress and exit-node
model. The app VirtualServices are retained as private Istio backend routing for
Octelium Services; the remaining Tailscale resources are non-app paths such as
CI/LAN reachability and reviewed webhook Funnel exceptions.

Remove or downgrade the Enterprise package through an Octelium-supported
package operation. Update the desired package version in this README and the
knowledge-base runbook before running the wrapper again.
