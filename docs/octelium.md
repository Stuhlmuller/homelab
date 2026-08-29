<!-- markdownlint-disable MD013 -->

# Octelium Access Plane

This repository uses Octelium for human access to homelab applications. App
hostnames keep their existing `*.stinkyboi.com` names. Exact Cloudflare DNS
records point those names at the public Cloudflare Tunnel, the tunnel forwards
them to the Octelium public ingress, and Octelium `WEB` Services proxy to the
existing Istio app routes. All app Services except AFFiNE enforce Octelium
login. AFFiNE permits anonymous transport so its native client can delegate
login to the application.

Human and Cordium Workspace Kubernetes access uses the private Octelium
`kubernetes-api.homelab` Service. CI uses the separate public, workload-only
`kubernetes-api-ci` Service. Tailscale remains deployed as a temporary
LAN/egress fallback, but it is not required for normal app or Kubernetes API
access.

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
forwarded to the in-cluster Istio gateway. Octelium authorizes app UIs as
clientless browser sessions; only the anonymous AFFiNE Service delegates user
authentication entirely to the application.

## Octelium Service Catalog

The external Octelium Cluster resources live at:

```text
docs/examples/octelium/homelab-services.yaml
```

They create:

- Core `ClusterConfig` `default`, raising the human session ceiling to 32 so
  disconnected CLI retries cannot exhaust the default 16-session allowance
  before its 16-hour sessions expire.
- Octelium Namespace `homelab` for the demo and Namespace `ci` for CI-only
  transport.
- Policy `homelab-human-web-access`, allowing authenticated human client
  sessions and clientless browser sessions to app `WEB` Services.
- Policy `homelab-cordium-user-access`, allowing only the dedicated
  `homelab-cordium-user` HUMAN identity to reach Cordium's package-managed
  `default.cordium` public `WEB` Service. The catalog attaches this policy to
  that dedicated repo-owned User because the system Service cannot be edited.
- Policy `homelab-workload-web-serve`, reserved for the
  `homelab-octelium-client` workload User if future Services need connector
  served upstreams.
- Policy `homelab-private-kubernetes-access`, allowing the `homelab-owner`
  client full operator access. `homelab-cordium-user` can only make
  namespace-scoped `get`, `list`, and `watch` requests for core Events, Pods,
  and Services; `apps/v1` workload controllers; and `batch/v1` Jobs and
  CronJobs. Five exact discovery paths are allowed. Everything else falls
  through Octelium's default deny.
- Policy `homelab-ci-kubernetes-api-access`, allowing only the
  `homelab-ci` workload User to create an Octelium client session and access
  the Kubernetes API Service.
- Workload User `homelab-octelium-client`, retained for connector bootstrap and
  future private upstreams.
- Workload User `homelab-ci` for GitHub Actions plan/apply and diagnostics,
  with matching 30-day clientless-session and access-token lifetimes. Rotate
  its credential every 21 days with `scripts/octelium-ci-credential.sh`.
- Dormant workload User `homelab-catalog-ci` for the protected private
  Kubernetes catalog workflow. Its helper-only Credential template lives in
  `homelab-private-kubernetes-ci-credential.yaml` outside this general catalog.
  The helper replaces the template's already-expired timestamp with a 30-minute
  expiry; the Credential auto-deletes when used, and its highest-priority inline
  policy denies everything except List/Create/Update for Policy and Service.
- Human User `homelab-e2e` for noninteractive app-access validation.
- Private `KUBERNETES` Service `kubernetes-api.homelab`, forwarding to
  `https://10.1.0.199:6443` for operator and restricted read-only Cordium
  access.
- Clientless `KUBERNETES` Service `kubernetes-api-ci`, forwarding to
  `https://10.1.0.199:6443` for CI Kubernetes API access.
- Public `WEB` Services `affine`, `argocd`, `compass`, `deluge`, `dispatcharr`,
  `grafana`, `kiali`, `litellm`, `n8n`, `nofx`, `octobot`, `openclaw`,
  `policy-bot`, `prowlarr`, `radarr`, and `sonarr`. Their public FQDNs are the
  existing app hostnames, such as `https://grafana.stinkyboi.com`.
- The `affine` Service sets `isAnonymous: true`. AFFiNE Desktop uses a native
  `assets://.` origin and must directly reach its server-discovery, login,
  GraphQL, blob, and Socket.IO endpoints. AFFiNE signup stays disabled after
  account bootstrap, so existing AFFiNE credentials remain the boundary.
- The `nofx` Service requires `homelab-human-web-access` before forwarding to
  NOFX, whose own login remains a second authentication boundary.
- Package-managed public `WEB` Service `default.cordium`, created by Cordium
  genesis with primary hostname `cordium`. Do not also declare a `cordium`
  Service in Octelium's default Namespace; both derive
  `cordium.stinkyboi.com` and make the ingress reject its routing snapshot.
- Cordium-specific identities: HUMAN User `homelab-cordium-user` for browser
  workspace access and WORKLOAD User `homelab-cordium-agent` for agent API
  automation through Cordium's package-managed API, plus the matching
  `cordium-users` and `cordium-agents` Groups those Users reference.
- WEB Service `homelab-demo.homelab` for service-proxy smoke tests.

The Enterprise console hostname `https://console.stinkyboi.com` is not an
Octelium app catalog Service. The public tunnel forwards it to the Istio
gateway, and the `octelium-cluster` `VirtualService` routes it to the
package-owned `console.octelium` backend without exposing the nested
`console.octelium.stinkyboi.com` hostname.

Each repo-defined app `WEB` Service forwards HTTPS to the in-cluster Istio gateway while
setting `Host`, `X-Forwarded-Host`, `X-Forwarded-Port`, and
`X-Forwarded-Proto` for the original app hostname. The HTTPS hop avoids the
gateway's HTTP-to-HTTPS redirect loop for authenticated clientless browser
requests. The header block also sets `forwardedMode: TRANSPARENT` so Octelium
preserves those explicit forwarded headers instead of deriving them from the
internal upstream. That keeps each app's existing Istio `VirtualService` and
base URL intact while moving the user-facing authentication layer to Octelium
clientless access. AFFiNE instead owns its user-facing authentication, and
Cordium's package-managed `default.cordium` Service terminates its Octelium
route directly.

Apply the service catalog to the Octelium Cluster:

```sh
octeliumctl apply --domain stinkyboi.com \
  --include ClusterConfig \
  docs/examples/octelium/homelab-services.yaml
octeliumctl apply --domain stinkyboi.com docs/examples/octelium/homelab-services.yaml
```

`--include ClusterConfig` overrides the normal apply include list, so keep the
second command to apply the catalog's other resource kinds.

Never add `--prune` to that command: this catalog is not an exhaustive list of
every non-system resource in the Octelium Cluster. Routine changes to the
private Kubernetes Policy or Service use the protected
`octelium-private-kubernetes-apply.yml` workflow documented in
`docs/ci-cd.md`. It extracts only those two objects, uses a one-authentication
Credential, and requires a second no-change apply. IdentityProvider, User,
Namespace, ClusterConfig, and other Credential changes still use the
authenticated operator path above. Never apply the helper-only Credential
template directly; its committed timestamp is deliberately expired.

When upgrading a Cluster
that previously applied the repo-defined Cordium Services, first apply the
updated catalog and then remove only the obsolete duplicates:

```sh
if octeliumctl get service cordium.default --domain stinkyboi.com >/dev/null 2>&1; then
  octeliumctl delete service cordium.default --domain stinkyboi.com
fi
if octeliumctl get service cordium-agent-api.homelab --domain stinkyboi.com >/dev/null 2>&1; then
  octeliumctl delete service cordium-agent-api.homelab --domain stinkyboi.com
fi
```

Cordium is bootstrapped after that catalog exists. The `cordium` Argo CD
Application first converges the network, secret, and host prerequisites, then
creates the `cordium-bootstrap` child Application at Sync wave 1. The child
runs upstream `cordium-genesis init` from a pinned
`ghcr.io/octelium/cordium-genesis:0.12.7` image and routes the public
`https://cordium.stinkyboi.com` browser path plus workspace app subdomains under
`*.cordium.stinkyboi.com` through the package-managed Octelium
`default.cordium` WEB Service, whose primary hostname is `cordium`. Browser
access is scoped to the dedicated `homelab-cordium-user` HUMAN identity by the
User-attached `homelab-cordium-user-access` policy. Agent automation should use a credential
for `homelab-cordium-agent` scoped to `homelab-cordium-agent-api-access`; do
not reuse the human browser identity for automated workspace runs. A PostSync
hook applies the repo-owned Cordium `ClusterConfig`, which sends new Workspace
PVCs to the disposable `cordium-local` StorageClass on `zimaboard-1`. Its
ExternalSecret polls the current agent credential from SSM every five minutes
so replacing the bootstrap placeholder is reconciled without another git
change. A repo-owned DaemonSet uses a root init container with access only to
the user-namespace sysctl file on `zimaboard-1` to converge the value required
by Cordium's rootless Podman runtime whenever GitOps or a node reboot recreates
the Pod; the Talos worker patch remains the machine-config source of truth. The
genesis hook pins the image's numeric non-root identity and carries
bootstrap-only RBAC `bind` and `escalate` on Roles and ClusterRoles because
upstream Cordium creates managed RBAC such as `cordium-nocturne` before the
long-running controllers exist. The parent waits for its normal wave to become
healthy before creating the child, so a stalled prerequisite cannot create the
identity. The child starts with a fresh 15-minute operation timeout, creates
that identity at PostSync wave -1, and runs genesis at wave 0. Genesis fails
after 12 minutes, leaving three minutes for its SyncFail cleanup. The same
cleanup Job runs at PostSync wave 1 after success and as a SyncFail hook after
failure, deleting only the named genesis ServiceAccount, ClusterRole, and
ClusterRoleBinding. Its persistent cleanup RBAC has `delete` on
`resourceNames: [cordium-genesis]` and cannot create, bind, or escalate
arbitrary RBAC. An ordinary failed child sync runs cleanup and removes the
identity. In-operation retries are disabled because they share the original
timeout start; the next new full `cordium-bootstrap` sync gets a fresh budget
and recreates the identity immediately before genesis.
Developer shell access should use the Octelium-backed Cordium browser route and
workspace subdomains, while agent automation uses the separate workload
identity with access restricted to the package-managed Cordium
`ManagementService`.

## Private Kubernetes Access

The private `kubernetes-api.homelab` Service is the normal operator path. It
<!-- checkov:skip=CKV_SECRET_6:Public name of an Octelium Secret, not secret data. -->
reuses the existing server-side Octelium Secret `homelab-ci-kubeconfig`; the
upstream kubeconfig stays inside Octelium and is never copied to the client or
committed to this repository. The Service uses that kubeconfig's cluster CA;
do not add `insecureSkipVerify`.

Recreating that shared Secret briefly affects this private Service and the CI
Service, so validate both after rotation.

From an operator workstation, install the current
[Octelium CLI](https://octelium.com/docs/octelium/latest/install/cli/install)
and [Cordium CLI](https://octelium.com/docs/cordium/latest/use/cli) first. They
are not included in this repository's Nix shell.

```sh
octelium login --domain stinkyboi.com
octelium connect --domain stinkyboi.com --ip-mode=v4 -d
octelium config kubernetes-api.homelab --domain stinkyboi.com
```

Run the `KUBECONFIG` export printed by `octelium config`, then restrict the
generated file and verify the private path:

```sh
chmod 0600 "$KUBECONFIG"
kubectl --request-timeout=15s get nodes
# Run after finishing Octelium-backed work.
octelium disconnect --domain stinkyboi.com
```

`octelium config` does not replace `~/.kube/config`, which the repository's
local Kubernetes and Helm providers read. Keep protected Terragrunt applies in
CI unless the Octelium context is deliberately merged into that file.

For an in-cluster developer shell, start a named Cordium Workspace. Evidence
runs must omit `--rm`; retain the named Workspace until owner-authenticated
server-side AccessLog attestation under issue `#879` passes:

```sh
reviewed_commit="$(git rev-parse HEAD)"
boundary_workspace="octelium-boundary-$(date -u +%Y%m%d%H%M%S)"
cordium run "$boundary_workspace" --domain stinkyboi.com \
  --repository https://github.com/Stuhlmuller/homelab.git \
  --checkout "$reviewed_commit"
```

Each running Workspace already has its own Octelium client session. Inside the
Workspace, run `octelium config kubernetes-api.homelab --domain
stinkyboi.com`, run the printed `KUBECONFIG` export, set it to mode `0600`, and
use an explicit namespace. The exact Cordium resource surface is core/v1
`events`, `pods`, and `services`; apps/v1 `daemonsets`, `deployments`,
`replicasets`, and `statefulsets`; and batch/v1 `cronjobs` and `jobs`. Only
`/api`, `/api/v1`, `/apis`, `/apis/apps/v1`, and `/apis/batch/v1` non-resource
discovery requests are allowed. The policy accepts those reads in any one
explicit namespace; all-namespaces reads and all subresources are denied.

Octelium v0.35 derives the policy fields from its
[Kubernetes request parser](https://github.com/octelium/octelium/blob/v0.35.0/cluster/vigil/vigil/modes/httpg/httputils/k8s.go)
and maps them into `ctx.request.kubernetes` in
[Vigil pre-authorization](https://github.com/octelium/octelium/blob/v0.35.0/cluster/vigil/vigil/modes/httpg/middlewares/preauth/preauth.go).
Its [policy evaluator](https://github.com/octelium/octelium/blob/v0.35.0/cluster/octovigil/octovigil/policy.go)
returns `DENY` when no rule matches. Keep the catalog fields aligned with that
version until the Octelium upgrade is complete. The v0.35
[Kubernetes denial handler](https://github.com/octelium/octelium/blob/v0.35.0/cluster/vigil/vigil/modes/httpg/middlewares/auth/denied.go)
sets Status reason `Forbidden`, message `Octelium: Unauthorized request`, and
HTTP code 403; kubectl renders those fields as the exact marker used below.

Verify the boundary from two separate active sessions. Do not run this in
GitHub Actions: a workflow would need a persistent HUMAN credential, cannot
complete the Entra browser login, and would publish sensitive evidence. The
script verifies the exact Octelium User is `HUMAN`, the Session is connected
and `CLIENT`, and the supplied kubeconfig exactly matches Octelium v0.35's
single `kubernetes` cluster, `kubernetes-admin` placeholder-token user, and
`kubernetes-admin@kubernetes` context. Its only server may be
`https://kubernetes-api.homelab.local.stinkyboi.com:6443`; alternate
credentials, proxy configuration, TLS bypass, and extra contexts fail before
the first Kubernetes request. Every `octelium` and `kubectl` proof child drops
inherited upper- and lower-case HTTP, HTTPS, and ALL proxy variables. The
15-second `octelium status` preflight also clears inherited authentication
tokens and assertions, pins Cordium to its package-owned
`/var/run/octelium-proxy.sock`, and removes that socket override for owner. It
runs only with child-local `OCTELIUM_CONTAINER_MODE=true`: an existing database
session may transparently refresh its access token, but a missing or expired
session cannot start another authentication flow and fails the run.

Start only from a clean checkout at the reviewed commit. Before either boundary
run, complete `scripts/octelium-e2e-check.sh` at that same commit and require
both `PASS: Octelium private Kubernetes Policy declaration matches the
repository catalog` and the final pass result. This live catalog equality gate
is a prerequisite, not evidence that the request boundary works. The boundary
script then fails closed on tracked or untracked checkout changes and records
the caller's unique evidence ID, exact commit, plus SHA-256 digests of itself and
`docs/examples/octelium/homelab-services.yaml` in private `metadata.tsv`.

First sign in to `https://cordium.stinkyboi.com` as the Entra identity mapped
at runtime to `homelab-cordium-user`, enter the retained named Workspace, and run
these commands inside it:

```sh
octelium config kubernetes-api.homelab --domain stinkyboi.com
# Export the KUBECONFIG path printed above, then:
chmod 0600 "$KUBECONFIG"
cordium_evidence="${TMPDIR:-/tmp}/octelium-cordium-boundary-evidence"
boundary_evidence_id="PASTE_THE_EXACT_boundary_workspace_VALUE"
scripts/octelium-kubernetes-boundary-e2e.sh \
  --role cordium \
  --kubeconfig "$KUBECONFIG" \
  --evidence-dir "$cordium_evidence" \
  --evidence-id "$boundary_evidence_id"
```

The Cordium run executes every declared allowed resource and discovery family,
an exact Pod `get`, a timed `watch`, and strict denials for all-namespaces
reads; Namespaces, Endpoints, EndpointSlices, sensitive core, RBAC, storage,
cluster, authorization-review, CRD, existing custom, and unknown resources;
`get`, `list`, `watch`, `create`, `update`, `patch`, `delete`, and
`deletecollection`; log, exec, attach, Pod and Service proxy, port-forward,
token, status, and unknown subresources; future apps/v2; and metrics, debug,
readyz, OpenAPI, version, and non-GET discovery paths. Mutation probes use
Kubernetes server dry-run or an invalid body and cannot persist an object or
mint a token. A failed request counts as an Octelium denial only when kubectl
emits the exact v0.35 Status rendering `Error from server (Forbidden):
Octelium: Unauthorized request`; validation errors, `NotFound`, and generic
Kubernetes `Forbidden` responses do not pass. Denied reads use randomized
nonexistent names or label selectors. Their response bodies are streamed
through an exact-marker sanitizer and never written to evidence, even when a
policy regression exposes a Secret or Pod log.

Exit the Workspace without deleting it. From the operator workstation, use
Cordium 0.12.7's native recursive copy to retain the diagnostic output on
encrypted storage:

```bash
workspace_tmp="$(cordium exec "$boundary_workspace" --domain stinkyboi.com -- \
  sh -c 'printf %s "${TMPDIR:-/tmp}"')"
encrypted_evidence="/ABSOLUTE/PATH/ON/ENCRYPTED-STORAGE/$boundary_workspace"
mkdir -m 0700 "$encrypted_evidence"
cordium cp -r --domain stinkyboi.com \
  "$boundary_workspace:$workspace_tmp/octelium-cordium-boundary-evidence/" \
  "$encrypted_evidence/"
```

Retain the named Workspace. Its privileged root process can fabricate or replay
every copied file, digest, timestamp, commit, and nonce, so those artifacts
cannot authorize deletion. Deletion remains blocked until an owner-authenticated
operator can query Octelium's server-side AccessLogs and match the exact
challenge-bound request matrix independently of the Workspace. Issue `#879`
owns that attestation gate.

Separately, log in as `homelab-owner` on the operator workstation, establish
the normal client connection, and generate a fresh kubeconfig:

```sh
octelium login --domain stinkyboi.com
octelium connect --domain stinkyboi.com --ip-mode=v4 -d
octelium config kubernetes-api.homelab --domain stinkyboi.com
# Export the KUBECONFIG path printed above, then:
chmod 0600 "$KUBECONFIG"
owner_evidence_root="/ABSOLUTE/PATH/ON/ENCRYPTED-STORAGE"
owner_evidence="$(mktemp -d "$owner_evidence_root/octelium-owner-boundary.XXXXXX")"
owner_evidence_id="$(basename "$owner_evidence")"
scripts/octelium-kubernetes-boundary-e2e.sh \
  --role owner \
  --kubeconfig "$KUBECONFIG" \
  --evidence-dir "$owner_evidence" \
  --evidence-id "$owner_evidence_id"
octelium disconnect --domain stinkyboi.com
```

Both evidence directories must be empty, absolute paths outside the checkout.
They are created with mode `0700`; result files use the process's `0077` umask.
Raw identity output is streamed through the validator and never written; only
the expected identity fields are retained.
Retain them only on encrypted operator-owned storage. Never attach them to a
GitHub issue or pull request, upload them as an Actions artifact, or commit
them. Treat both as diagnostic observations, not independently attested proof.
Record only the run timestamp, repository commit, and pass/fail result in the
issue. The two sessions must pass at the same reviewed catalog revision;
catalog JSON equality, copied evidence, and the repository jq/CEL model are
drift checks, not live enforcement proof.

If this boundary blocks a required diagnostic after rollout, use a reviewed
catalog change to remove both Cordium `ALLOW` rules while retaining
`operator-client`, then reapply the catalog. That safely disables Workspace
Kubernetes access. Do not roll back to a resource denylist; add a specific
group, version, and resource only after review.

Neither path needs the Tailscale subnet route.

This Service covers Kubernetes only. Octelium has no Talos-native Service
mode; `talosctl` still needs `.talos/talosconfig` and a separately validated
private transport. Keep Tailscale available as the temporary Talos/LAN fallback
until that path is replaced and tested.

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
`isPublic: true`, or if the public hostname returns a routing 404. It requires
AFFiNE's Service to remain anonymous, requires NOFX to use
`homelab-human-web-access`, and verifies that unauthenticated NOFX requests are
denied. It also checks the AFFiNE native-client CORS preflight and public
`serverConfig` GraphQL query. A negative workspace query must still return
AFFiNE's `AUTHENTICATION_REQUIRED` error, and all other app Services must remain
non-anonymous.

The gate also compares the live private Kubernetes Policy with the repository
catalog. That comparison detects declaration drift only; it does not prove an
authorization decision. Run `scripts/octelium-kubernetes-boundary-e2e.sh`
separately for both HUMAN/CLIENT identities before closing the access boundary.
Use `scripts/octelium-e2e-check.sh --catalog-check-only --catalog <path>` for a
non-live parser check; missing, malformed, and duplicate policy documents emit
an explicit `FAIL:` and the normal final summary.

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
  exists in the Octelium Cluster, and
  Cordium's generated `default.cordium` Service is present without a duplicate
  primary hostname;
- `kubernetes-api.homelab` is a private `KUBERNETES` Service;
- IdentityProvider `entra` exists in the Octelium Cluster;
- each existing app hostname resolves publicly through Cloudflare and responds
  over HTTPS without `octelium connect`; the Enterprise console check must not
  redirect to `console.octelium.stinkyboi.com`;
- a synthetic `tls-audit.cordium.stinkyboi.com` workspace hostname completes
  edge TLS and reaches Cordium's wildcard route;
- AFFiNE's native `assets://.` origin can preflight and query `serverConfig` at
  `https://affine.stinkyboi.com/graphql`, while an anonymous workspace query is
  denied by AFFiNE;
- reviewed callback hostnames `n8n-webhook.stinkyboi.com` and
  `policy-bot-hook.stinkyboi.com` resolve publicly and reach their path-limited
  callback routes.

Keep per-app `VirtualService` objects as private Istio backend routes for the
Octelium `WEB` Services. CI Kubernetes access now uses the `kubernetes-api-ci`
Octelium Service, and reviewed external callbacks use the `octelium-public`
tunnel with path-limited Istio routes. If the gate fails, treat the failure
output as the repair work queue.

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
octeliumctl apply --include ClusterConfig docs/examples/octelium/homelab-services.yaml
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

Cloudflare Tunnel public-hostname routes do not support gRPC streams. The CLI
API hostname therefore uses a separate direct origin: clients reach
Cloudflare on TCP/443, a hostname-specific Origin Rule changes the destination
port to `8443`, and the Xfinity gateway maps that port to
`10.1.0.200:30443`. The dedicated `octelium-api-ingressgateway` accepts
Cloudflare origin TLS without SNI, while a separate `VirtualService` routes
only the API Host. Run
`scripts/octelium-public-dns.sh` from the homelab LAN after the
`octelium-api-upnp` CronJob creates its leased router mapping. The script
verifies both that mapping and an unauthenticated `grpc-status: 16` response
from the NodePort before changing DNS. All browser, app, and callback hostnames
remain on `octelium-public`.

The repository-owned CronJob renews the lease but cannot enable UPnP on the
Xfinity gateway. Router account authority must enable UPnP or provide a
reviewed static TCP/8443 forward before rollout validation can pass. Grafana
alerts when the last successful renewal is stale or absent. The end-to-end
check resolves the API hostname through `1.1.1.1` and pins its gRPC request to
that public address so Octelium split DNS cannot mask a broken WAN edge.

Reconcile the Cloudflare origin-port and TLS Configuration Rules through their
protected workflow so the token remains masked inside the `homelab-production`
environment:

```sh
gh workflow run octelium-cloudflare-origin-port.yml --ref main
```

The workflow sets Full (strict) SSL for only the Octelium API hostname and
verifies that the zone allows HTTP/2 to the origin; Octelium's TLS gRPC endpoint
requires both. Its token needs zone read, Zone Settings read, Origin Rules edit,
and Config Settings write for `stinkyboi.com`.

Once the API and gRPC path are true, create or rotate the
`homelab-octelium-client` credential, store it in SSM, bump
`remoteRef.version` on `octelium-client-auth`, update the ExternalSecret target
Secret name to match that SSM version, bump
`homelab.rst.io/octelium-credential-ssm-version` on both the ExternalSecret and
the connector pod annotations, sync the `octelium` Argo CD Application, then
run `scripts/octelium-e2e-check.sh`.

After the Octelium Gateways report public addresses, reconcile exact Cloudflare
DNS records for their `_gw-*` hostnames when gateway hostnames are needed, then
publish the control-plane, app, and external callback hostnames through the
public Cloudflare Tunnel:

```sh
scripts/octelium-gateway-dns.sh --dry-run
scripts/octelium-gateway-dns.sh
scripts/octelium-public-dns.sh --dry-run
scripts/octelium-public-dns.sh
```

When off the homelab LAN, reconcile only the public-tunnel records without
changing the API A record or bypassing its UPnP safety gate:

```sh
scripts/octelium-public-dns.sh --tunnel-only --dry-run
scripts/octelium-public-dns.sh --tunnel-only
```

The gateway reconciler prevents `_gw-*` names from falling through to stale
wildcard records. The public reconciler verifies the CronJob-owned API mapping,
creates its proxied A record, then creates exact proxied CNAME records to the named Cloudflare
Tunnel target for `stinkyboi.com`, portal and browser aliases,
`console.stinkyboi.com`, app hostnames such as `grafana.stinkyboi.com`, and
callback hostnames such as `n8n-webhook.stinkyboi.com` and
`policy-bot-hook.stinkyboi.com`.
`--tunnel-only` skips the API hostname entirely; a later full run from the
homelab LAN remains responsible for verifying and reconciling that record.

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

During the August 2026 two-node dataplane outage,
`clusters/homelab/apps/octelium-enterprise/emergency-dataplane.yaml` provides a
bounded fallback on `acer`. It restores the ingress and shared authorization
service, the Portal and API control paths, OctoBot, the CI Kubernetes API, and
18 additional public WEB Services—19 public WEB fallbacks including
OctoBot—without adding the control-plane node to the native dataplane pool. The
fallback service Pods use only the primary
Kubernetes network and reuse the existing generated Service selectors;
`default.cordium` and `console.octelium` include their required managed
sidecars. Refresh a fallback UID whenever Octelium recreates its Service.

Do not remove the fallback after a single worker becomes Ready. Use the
capacity, 24-hour native-fleet stability, direct native Pod probe, and public
end-to-end gates in
`docs/knowledge-base/architecture/cluster-topology.md`.

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
client use `octelium-api.stinkyboi.com`. The Istio origin certificate needs
apex plus first-level `*.stinkyboi.com` coverage. Cloudflare edge TLS also
needs an advanced `*.cordium.stinkyboi.com` wildcard for workspace hosts.

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
| `zimaboard-1` | `octelium.com/node-mode-controlplane=`, `octelium.com/node-mode-cordium=` |
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
`homelab.rst.io/cordium-genesis-revision` on the genesis Job and tracked cleanup
ServiceAccount when the hook template needs to be recreated. The latter change
starts a full `cordium-bootstrap` sync; selective sync does not run the PostSync
or SyncFail hooks that bound the bootstrap privilege.

## Validation

Before rollout:

```sh
kubectl kustomize clusters/homelab/apps/octelium
kubectl kustomize clusters/homelab/apps/octelium-cluster
kubectl kustomize clusters/homelab/apps/octelium-storage
kubectl kustomize clusters/homelab/apps/istio
kubectl kustomize clusters/homelab/platform/multus
bash -n scripts/octelium-gateway-dns.sh
bash -n scripts/octelium-public-dns.sh
bash -n scripts/octelium-cloudflare-origin-port.sh
bash -n scripts/octelium-entra-oidc.sh
scripts/octelium-cluster-bootstrap.sh --help
scripts/octelium-enterprise-package.sh --help
scripts/octelium-e2e-check.sh --help
scripts/octelium-kubernetes-boundary-e2e.sh --help
bash scripts/ci/octelium-kubernetes-boundary-e2e-check.sh
```

After activation:

```sh
kubectl -n argocd get application cordium cordium-bootstrap
kubectl -n argocd get application cordium-bootstrap \
  -o jsonpath='{.status.operationState.phase}{"\n"}'
kubectl -n octelium get serviceaccount cordium-genesis
kubectl get clusterrole/cordium-genesis clusterrolebinding/cordium-genesis
kubectl auth can-i --as=system:serviceaccount:octelium:cordium-genesis create clusterrolebindings
kubectl get storageclass cordium-local
cordium man get clusterconfig -o yaml
kubectl -n octelium-client get externalsecret,secret octelium-client-auth
kubectl -n octelium-client get deploy,pod -l app.kubernetes.io/instance=octelium-client
kubectl -n octelium-client logs deploy/octelium-client
scripts/octelium-gateway-dns.sh --dry-run
scripts/octelium-public-dns.sh --dry-run
scripts/octelium-e2e-check.sh \
  --octelium-context <octelium-cluster-context> \
  --homelab-context <homelab-context>
```

Successful hook Jobs are deleted by `HookSucceeded`; inspect Jobs and logs only
during an active or failed child operation. After a successful full child sync,
or a failed sync whose SyncFail cleanup completed, the genesis identity lookups
must return `NotFound` and the authorization check must print `no`. If
control-plane or scheduler failure also prevented cleanup, recover it, inspect
the resources, and start a full `cordium-bootstrap` sync; cleanup is idempotent.

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

The app hostnames publish exact proxied Cloudflare Tunnel CNAMEs, so human
browser access can reach Octelium clientless `WEB` Services without first
running `octelium connect`. CLI VPN sessions still use
`octelium-api.stinkyboi.com` and the Octelium Gateway records.

The `octelium-public` tunnel is also the reviewed backbone for unauthenticated
external callbacks that cannot complete an Octelium browser login, currently
`n8n-webhook.stinkyboi.com` and `policy-bot-hook.stinkyboi.com`. Keep those
callback `VirtualService` objects path-limited and annotated with
`homelab.rst.io/public-callback: "true"` plus a reviewed purpose.

Check the CI Kubernetes API Service through Octelium from a client machine:

```sh
KUBE_API_SERVER_URL=https://kubernetes-api-ci.stinkyboi.com \
OCTELIUM_AUTH_TOKEN=<octelium-clientless-access-token> \
bash scripts/ci/install-kubeconfig.sh
kubectl --request-timeout=15s version
```

The `homelab-ci-kubernetes-api-access` policy is the enforcement boundary for
this clientless workload credential. The upstream kubeconfig lives only in the
Octelium Secret `homelab-ci-kubeconfig`, created with
`scripts/octelium-ci-kubeconfig-secret.sh --kubeconfig <path>`. GitHub Actions
uses the access token as the public Service bearer credential, avoiding the
IPv6-only Gateway transport entirely. The rotation helper deletes this
dedicated User's old Sessions before issuing the replacement, so Octelium
creates a fresh 30-day Session instead of reusing the prior expiry.

## Rollback

Roll back the Cordium storage default through
`clusters/homelab/apps/cordium-bootstrap/cluster-config.yaml`: remove the
storage rule or point it at a reviewed replacement, merge, and let Argo CD
rerun the full child lifecycle and then its ClusterConfig PostSync hook.
Existing Workspace PVCs do not migrate; recreate only disposable Workspaces
that should use the replacement. Remove the `cordium-local` provisioner only
after no PVC references it.

For full Cordium retirement, remove `cordium-bootstrap-application.yaml` from
the parent Kustomization and sync `cordium` before deleting the parent
Application. The child Application's foreground resources finalizer cascades
its tracked bootstrap resources, preventing an orphaned genesis identity.

Set the connector Deployment replicas to `0` and sync the `octelium` Argo CD
Application. That stops the connector without restoring Tailscale Funnel.

If the external resources are no longer wanted, delete the homelab Services,
the `homelab-octelium-client` User, the `homelab-ci` User, and the
homelab Policies
from the Octelium Cluster with `octeliumctl`. Do not reintroduce Tailscale
Funnel during rollback; external callback routes should either stay on
`octelium-public` or be removed until a replacement is reviewed. The Tailscale
LAN/exit-node utility is separate from the Octelium app, callback, VPN, and CI
backbone.

Remove or downgrade the Enterprise package through an Octelium-supported
package operation. Record the target package version in this document before
running the operator script again.
