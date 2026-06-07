# Octelium

Tags: #runbooks #octelium #networking #secrets

Source: `docs/octelium.md`

## Model

Octelium is the replacement target for human access to homelab applications.
The current app registration is `octelium`, the Kubernetes namespace is
`octelium-client`, and app UI routes now use Octelium-backed
`*.stinkyboi.com` hostnames. Tailscale can still have separate non-app duties,
such as CI cluster reachability or reviewed public webhook exceptions, until
those are replaced in their own change.

The Argo CD Application installs repo-owned support manifests, including the
`octelium-client` connector Deployment. The connector runs in TUN mode with
`NET_ADMIN` and `MKNOD`, is enrolled in Istio ambient mesh, and runs after the
Octelium API, service catalog, and workload credential are verified. It maps
`octelium-api.stinkyboi.com` to the internal Istio gateway so the in-cluster
connector does not depend on Cloudflare gRPC proxying.

## Service Catalog

`docs/examples/octelium/homelab-services.yaml` is the Octelium Cluster resource
catalog. It creates Namespace `homelab`, Policy
`homelab-human-web-access`, Policy `homelab-workload-web-serve`, workload User
`homelab-octelium-client`, human e2e User `homelab-e2e`, TCP/443 Services for
Argo CD, Compass, Deluge, Grafana, Kiali, LiteLLM, n8n, OctoBot, OpenClaw,
Policy Bot, Prowlarr, Radarr, and Sonarr, plus WEB Service
`homelab-demo.homelab`. App services keep valid internal Octelium names such
as `grafana.homelab` and carry
`spec.attrs.appHostname` values such as `grafana.stinkyboi.com`.

The policy allows authenticated human client sessions to app Services in those
namespaces. The workload policy allows the single
`homelab-octelium-client` workload User to serve those Services. CI owns a
separate workload User `homelab-ci`, Policy
`homelab-ci-kubernetes-api-access`, and TCP Service
`kubernetes-api.homelab -> tcp://10.1.0.199:6443`; GitHub Actions uses that
Service as the transport path for live Terragrunt plan/apply and diagnostics.
The app Services forward TCP/443 to the in-cluster Istio gateway, preserving
existing `https://*.stinkyboi.com` URLs, SNI routing, and the wildcard
certificate while moving the network path onto Octelium. The Kubernetes
connector serves the app service list with
`--scope=api:user.MainService/Connect` and matching `--scope=service:<name>`
flags. The per-app Istio `VirtualService` objects remain as private backend SNI
routes for these TCP Services and are annotated with
`homelab.rst.io/access-plane: octelium`.

## Microsoft Entra Login

Octelium portal login uses IdentityProvider `entra`. The Microsoft Entra app is
managed by `IaC/live/azuread-applications/octelium`, registers
`https://stinkyboi.com/callback` and
`https://portal.stinkyboi.com/callback`, and writes generated client
material to `/homelab/octelium/entra/*` in SSM. After that unit applies,
`scripts/octelium-entra-oidc.sh` reads those SSM values, refreshes Octelium
native Secret `entra-oidc-client-secret`, and applies the IdentityProvider.
Pass `--admin-user-name` and `--admin-email` only at runtime when adding the
operator HUMAN user mapping; keep personal Entra identifiers out of git.

The IdentityProvider requests `openid`, `email`, and `profile`, uses Entra
`preferred_username` as the login identifier, and does not require
`email_verified`, which Entra may omit. If the portal shows
`No Available Identity Providers`, verify
`octeliumctl get identityprovider entra --domain stinkyboi.com`
before changing the app service catalog.

## Enterprise Package

Octelium Enterprise is represented by the `octeliumee` package from
`https://github.com/octelium/octelium-ee`. It installs into an already running
Octelium Cluster with `octops`; it is not Argo CD-synced Kubernetes desired
state and it does not replace the `octelium-client` connector in this homelab.

Current desired package version: `0.22.0`.

The Octelium Cluster domain is `stinkyboi.com`, which makes the client contact
`octelium-api.stinkyboi.com`. `octelium.stinkyboi.com` is a public alias for
the Octelium control plane, not the CLI domain. This keeps the public API and
portal names on the Cloudflare Universal SSL shape: apex `stinkyboi.com` plus
first-level `*.stinkyboi.com`.

Install or upgrade with:

```sh
scripts/octelium-enterprise-package.sh \
  --domain stinkyboi.com \
  --version 0.22.0

scripts/octelium-enterprise-package.sh \
  --domain stinkyboi.com \
  --version 0.22.0 \
  --upgrade
```

The operator workstation needs `octops` `v0.29.0` or later and kubeconfig
access to the Octelium Cluster. Keep commercial or production license material
outside git; add only safe references or secret contracts here.

## Bootstrap Access

The steady-state bootstrap path for users outside the tailnet is the
`octelium-public` Cloudflare Tunnel connector. It exposes only `stinkyboi.com`,
`octelium.stinkyboi.com`, `portal.stinkyboi.com`, and
`octelium-api.stinkyboi.com` to the public Internet and forwards those
hostnames to the existing Istio `octelium-cluster` route. The Cloudflare Tunnel
credentials JSON and UUID live outside git in
`/homelab/octelium/cloudflare-tunnel-credentials-json` and
`/homelab/octelium/cloudflare-tunnel-id`; both are rendered by the
`octelium-public-cloudflared-credentials` ExternalSecret. After those SSM values
exist, run `scripts/octelium-public-dns.sh` to replace the old tailnet DNS
answers with exact proxied CNAMEs to the Cloudflare Tunnel target. Cloudflare
edge TLS only needs the apex plus first-level `*.stinkyboi.com` names.

Octelium CLI and VPN sessions use gRPC on `octelium-api.stinkyboi.com`.
Cloudflare returns HTTP `403` to gRPC requests when zone gRPC is disabled, and
the request is rejected before it reaches `cloudflared`. Store a Cloudflare API
token with `Zone:Read` and `Zone Settings:Edit` in
`/homelab/octelium/cloudflare-zone-settings-token`, then run
`scripts/octelium-cloudflare-grpc.sh` before the e2e gate. The cert-manager
DNS-01 token is intentionally too narrow and returns Cloudflare error `9109`.

If public DNS or VPN access to the Octelium Cluster is not available yet,
bootstrap the UI and API through a local port-forward to the Octelium Cluster
ingress:

```sh
kubectl -n octelium get svc
sudo kubectl -n octelium port-forward svc/<octelium-ingress-service> 443:443
```

On the bootstrap workstation only, add temporary host entries for:

```text
octelium.stinkyboi.com
stinkyboi.com
portal.stinkyboi.com
octelium-api.stinkyboi.com
```

Then run `octelium login --domain stinkyboi.com`, apply
`docs/examples/octelium/homelab-services.yaml`, create the
`homelab-octelium-client` credential, store it in SSM, and sync the Argo CD
Application. Remove the temporary host entries after real DNS or the first VPN
path reaches the same Octelium ingress.

## Cutover Gate

`scripts/octelium-e2e-check.sh` is the required gate for Octelium app access.
It checks the Octelium control-plane namespace, IdentityProvider `entra`,
the synced workload credential, a ready `octelium-client` replica, non-Istio
responses from the Cluster/API/portal hostnames, every homelab app Service in
the Octelium catalog, exact `AAAA` DNS for each existing app hostname, and
HTTPS access to each app through its matching Octelium Service. The
app-hostname probe starts an Octelium client session, publishes each app
Service to a loopback port, curls the real `https://*.stinkyboi.com` URL with
SNI preserved by `curl --connect-to`, and verifies the public DNS record points
at an Octelium `fdee:b76e:*` IPv6 service address instead of the old Tailscale
wildcard. Noninteractive e2e runs need a HUMAN credential, such as one for
`homelab-e2e` with `homelab-human-web-access`; the workload credential is only
for serving.

Human client sessions that browse the existing app hostnames must use
`octelium connect --domain stinkyboi.com --ip-mode=both` or IPv6 because those
hostnames intentionally publish Octelium private `AAAA` records. IPv4-only
sessions are reserved for explicit publish workflows such as CI's
`kubernetes-api.homelab` loopback mapping.

When the Octelium control plane is external to homelab, run the gate with
separate `--octelium-context` and `--homelab-context` values so the
control-plane namespace checks and connector checks target the correct
clusters.

If the gate fails, treat the failure output as the remaining repair queue before
declaring app access healthy.

## Secret Contract

`octelium-client-auth` reads `/homelab/octelium/client-auth-token` from AWS SSM
and renders the versioned target Secret `octelium-client-auth-v5`.
The token is created with `octeliumctl create cred --user
homelab-octelium-client --policy homelab-workload-web-serve
homelab-octelium-client` and must stay outside git.
Do not attach `homelab-human-web-access` to this workload credential; that
Policy is intentionally human-only and denies `WORKLOAD` users.
When the SSM value changes, bump `homelab.rst.io/octelium-credential-ssm-version`
on both the `octelium-client-auth` ExternalSecret and the connector pod
annotations, bump the ExternalSecret `remoteRef.version` to the exact SSM
parameter version, and update the target Secret name to match that SSM version
so External Secrets creates a fresh Secret and Argo rolls the pod.

GitHub Actions CI uses a separate Octelium workload credential for User
`homelab-ci` and Policy `homelab-ci-kubernetes-api-access`. Store that
credential as GitHub environment secret `OCTELIUM_CI_AUTH_TOKEN` in both
`homelab-plan` and `homelab-production`; do not store it in AWS SSM unless a
future repo-owned workflow needs to materialize it in-cluster. The credential
must only publish Service `kubernetes-api.homelab` to the runner loopback
listener. Do not add Octelium `--scope` flags to this v0.35 auth-token connect
path; the workload policy is the hard access boundary and scoped sessions are
denied before publish starts.

## Isolation

The connector service-account principal is:

```text
cluster.local/ns/octelium-client/sa/octelium-client
```

Protected Istio ambient workloads that Octelium serves must allow that
principal in their `AuthorizationPolicy`. Workloads with Kubernetes
`NetworkPolicy` must also allow the relevant Octelium traffic source. The demo
allows both the connector pod and the generated `svc-homelab-demo-homelab`
proxy in the `octelium` namespace because WEB service proxy traffic reaches the
backend from that generated pod.

## Full Cluster Bootstrap

The in-homelab Octelium Cluster is bootstrapped by repo-owned prerequisites and
the Octelium-native `octops init` command. The steady-state prerequisites are:

- `platform-multus` in `clusters/homelab/platform/multus` for the
  Talos-compatible Multus thick DaemonSet.
- `IaC/live/kubernetes-node-labels` for
  `octelium.com/node-mode-dataplane=` on `zimaboard-0` and `zimaboard-2`, and
  `octelium.com/node-mode-controlplane=` on `zimaboard-1`.
- `octelium-storage` in `clusters/homelab/apps/octelium-storage` for
  PostgreSQL and Redis, with generated SSM passwords at
  `/homelab/octelium/postgres-password` and
  `/homelab/octelium/redis-password`.
- `octelium-cluster` in `clusters/homelab/apps/octelium-cluster` for the Istio
  `VirtualService` that routes the Cluster, portal, and API hostnames to the
  Octelium data-plane ingress service in front-proxy mode. The wrapper sets
  `OCTELIUM_INGRESS_FRONT_PROXY=true` for Octelium v0.35 and also keeps the
  older `OCTELIUM_FRONT_PROXY_MODE=true` compatibility name so the dataplane
  exposes cleartext HTTP on port `8080` behind the trusted Istio TLS edge. The
  same app owns a `DestinationRule` that upgrades Istio-to-Octelium upstream
  traffic to HTTP/2 so Octelium CLI gRPC calls keep their response trailers.
- `octelium-public` in `clusters/homelab/apps/octelium-public` for the
  Cloudflare Tunnel connector that exposes the Octelium control-plane,
  portal, and API hostnames outside the tailnet without exposing the app
  service hostnames.

The `octelium-cluster` Argo CD Application must not own the `octelium`
namespace. Octelium genesis deletes and recreates that namespace during
`octops init`, so the homelab keeps only the front-door `VirtualService` in
`istio-system` as repo-owned desired state. Automated pruning stays disabled on
that Application so Argo does not prune the formerly managed namespace during
the ownership handoff.

Run `scripts/octelium-cluster-bootstrap.sh --domain stinkyboi.com`
after those prerequisites are synced and healthy. The wrapper generates a
temporary bootstrap file from the Kubernetes Secret, runs `octops init` with
Octelium ingress front-proxy mode, labels the `octelium` namespace with the
privileged Pod Security profile required by the Octelium data plane, and waits
for the namespace workloads. When an Octelium deployment already exists, the
same wrapper runs `octops upgrade`, answers the upgrade confirmation, waits for
the newly created `octelium-genesis-upgrade-*` Job to complete, and then waits
on Kubernetes rollout status; it does not use Octelium's portal-authenticated
`octops upgrade --wait` mode.
- `scripts/octelium-gateway-dns.sh`, which reads the Cloudflare API token from
  SSM and reconciles exact `_gw-*` AAAA records from Octelium Gateway status so
  client VPN traffic does not fall through to the tailnet wildcard record.
- `scripts/octelium-app-dns.sh`, which reads Octelium Service status and
  reconciles exact app `AAAA` records like
  `grafana.stinkyboi.com -> fdee:b76e:...` so existing app hostnames route
  through Octelium VPN access without overlapping Tailscale IPv4 routes.

## Validation

Render the Kubernetes side with:

```sh
kubectl kustomize clusters/homelab/apps/octelium
kubectl kustomize clusters/homelab/apps/octelium-cluster
kubectl kustomize clusters/homelab/apps/octelium-public
kubectl kustomize clusters/homelab/apps/octelium-storage
kubectl kustomize clusters/homelab/platform/multus
bash -n scripts/octelium-entra-oidc.sh
bash -n scripts/octelium-cloudflare-grpc.sh
scripts/octelium-cluster-bootstrap.sh --help
scripts/octelium-enterprise-package.sh --help
scripts/octelium-e2e-check.sh --help
```

After activation, confirm External Secrets, the service catalog, and the
connector Deployment in `octelium-client`. Rotate the workload credential only
after `https://octelium-api.stinkyboi.com` serves the Octelium API,
not a generic Istio `404` or gRPC `Unimplemented` response. Stop the connector
by setting the connector Deployment replicas to `0`.

Rollback for the Enterprise package is an Octelium package operation, not an
Argo CD sync. Update the desired package version in this runbook first, then
run the wrapper with the intended `--version` and `--upgrade` flags.

## Failure Notes

If Argo CD is `Synced` but `Degraded`, inspect the child pods and events before
changing the Application. On June 6, 2026 the first rollout degraded because the
Podinfo demo had only `args: [--port=9898]`, which made containerd try to
execute the flag as the binary. The image's upstream Dockerfile sets
`WORKDIR /home/app` and `CMD ["./podinfo"]`, so the explicit command must be
`./podinfo` when passing custom args.

An early rollout started the connector before the external Octelium API was
verified. Keep the cluster domain at `stinkyboi.com` so the client calls
`octelium-api.stinkyboi.com`; using `octelium.stinkyboi.com` as the domain
would make clients call the nested `octelium-api.octelium.stinkyboi.com`
hostname that Cloudflare Universal SSL does not cover. The stable GitOps state
keeps the connector active only after the real Octelium API/package path is
ready and the API hostname serves Octelium instead of a generic Istio `404` or
gRPC `Unimplemented` response.

During full Cluster bootstrap, Multus must stay ready on every node that can
host Octelium service pods. A 50Mi daemon limit OOMKilled Multus on
`zimaboard-0` while it processed Octelium network attachments; the platform
manifest now uses a 128Mi request and 256Mi limit.
