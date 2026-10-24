# Enterprise Deployment, Access and Retirement Contract

Stock upstream is pinned to `33bb74590a749f37934da4502fca6035cd234a55`.
This contract adds repository orchestration around supported interfaces; it does
not patch Enterprise behavior or restore the legacy assistant into it.

## Desired State and API Reconciliation

`scripts/config/openclaw-enterprise.json` declares: schema version, pinned source
and images, installation phase, logical Namespace/agent names, private origins,
storage class, native model configuration, credential references, and
`activationEnabled`. It contains no secret values or operator shell inputs.
The source-to-image pairing policy and image repository names are fixed in T003.
Protected [publisher `40048058867`](https://github.com/Stuhlmuller/homelab/actions/runs/40048058867)
signed and fully pulled the paired controller/runtime and CLI images; their
verified digests are pinned in source. The CLI build pins the Go 1.27.1
toolchain and exact Linux amd64 binary hash from `cmd/occ`, then packages it
with the same source revision. Protected [full mirror `40011909180`](https://github.com/Stuhlmuller/homelab/actions/runs/40011909180)
verified the 214-image platform catalog. The journal operator image was also
published, but its digest remains unselected because the Installation and
values changed after that build; exact-source rebuild is required before use.
Activation remains false.

Initial state is inactive: stock Embedded OpenClaw, no channels, no Backend,
Sandbox, optional broker/collector, or configured Codex Harness. The pinned OCE
Kubernetes driver does not accept `openrouter` as a Harness provider. Use its
supported `openai` transport with `baseUrl: https://openrouter.ai/api/v1`,
`api: openai-completions`, and model ID `openrouter/free`. OCE's model reference
is `openai/openrouter/free`; the wire request to OpenRouter uses `openrouter/free`.
The first slash selects OCE's provider; raw `openrouter/free` would select the
unsupported `openrouter` provider. Test this mapping before writing a Configuration.
Do not copy the example model or reuse old app credentials. The dedicated
OpenRouter key must be registered as an Agent `harnessAuth` OCC Secret; direct
Configuration secret binding or an ExternalSecret model mount is unsupported.
OCE projects it as `OPENAI_API_KEY` only into this agent. Foundation,
Configuration and stopped Agent creation may proceed without the key. An
Agent deploy requires a bound Secret and runs a real provider probe; never
use it in the inactive phase.
The initial managed Configuration follows the pinned first-Agent helper:
OpenRouter uses the `openai` transport, `openrouter/free` wire model,
`OPENAI_API_KEY` env credential reference and narrow model secret provider;
tools are denied. Native `controlUi` starts disabled, with no localhost browser
origins. The origin is `null` in committed desired state until T048 returns it.

Planned `scripts/openclaw-enterprise.py` commands are `check`, `reconcile`, and
`verify`, each accepting `--config PATH`. `reconcile` also requires the protected
workflow's `--expected-sha SHA` and a mounted credential-file path. Read-only
commands never create an agent, deploy a revision, or send a model request.
Acceptance probes are separate declared tests, not implicit in read-only `verify`.

At pinned source `33bb745`, `GET /installation` exposes identity and optional
capabilities, but no selected Compute, Configuration, Secret, IAM or Sandbox
Driver identities/settings. `occ installation get` reads that same operation;
`installation deployment-inventory` only reports namespace/agent deployment
state. These reads cannot establish the intended Driver selection. The
repository-owned proof below instead binds the reviewed startup bytes to the
current controller workloads; without it, `check` and `reconcile` fail closed
before any API mutation. Capability support for Embedded is not that proof.

The chart provides a read-only Kubernetes proof path. T039 must declare the
exact reviewed `installation.yaml` bytes in source. A protected, exact-main,
repository-owned stage creates and re-reads a dedicated, version-named Opaque
Secret `occ-installation-startup-<first 32 SHA-256 hex characters>` with
`immutable: true` before Application registration; a raw Secret manifest is
forbidden by repository policy. T039 must
pair `installation.secretName` with `controlPlane.installationChecksum` set to
that full digest. After bootstrap, a protected T041 path sets and verifies the Secret's
`openclaw.dev/installation-id` annotation must equal `GET /installation`.
Before reconciliation, a protected reader must compare the Secret's exact
decoded bytes with the reviewed source and check both current, Ready API and
worker Pods: Deployment/ReplicaSet ownership, pinned controller image, exact
startup volume/key/path, checksum, and Pod creation after the immutable Secret.
Read the Secret and workload identities again after the Installation API read;
any changed UID, resource version or Pod identity blocks. Do not log the Secret
or candidate bytes. An immutable Secret must use a new name on rotation so an
old Pod cannot silently retain a deleted Secret mount.

`scripts/openclaw-enterprise.py check` gathers scoped Kubernetes snapshots
around `GET /installation` and applies the attestation. With a protected
credential file, exact main SHA and durable journal, `reconcile` can POST the
logical `claw` Namespace with `existingNamespace: openclaw-agents` after exact
Namespace, Pod Security, NetworkPolicy and RBAC preflight. It verifies the
ready API object and Kubernetes ownership before journaling its ID. With
`activationEnabled: false`, it creates or adopts one owned Agent Configuration
and one stopped Embedded Agent. `verify` reads their exact IDs, generation,
values, and stopped state without deploying or sending inference. A failed
`reconcile` can have made partial changes; preserve the journal for recovery.
`scripts/openclaw-enterprise-bind-installation.py` implements the post-bootstrap
annotation write as a source-only protected entrypoint. It requires exact-main
review, a private bootstrap key, two stable Ready-Pod proofs around the first
Installation API read, UID/resource-version JSON Patch tests, and a second
Installation API read with exact Secret readback. Its protected invocation and
the credential/deployment workflow remain pending.
The source-only active reconciler is gated by committed
`activationEnabled: false`; its tested API path does not register or deploy an
agent until a later reviewed config and exact-main workflow enable it.
Before any active write, the full Agent read must show no plugins, approvers,
repository access or bindings, or credential sources. Verify the same absence
in the admitted revision snapshot; an unreadable saved-settings variant blocks.

After a blocked `reconcile`, inspect the protected journal's `namespaceId`,
`GET /namespaces/:id`, and the owned `openclaw-agents` Namespace/NetworkPolicies
with read-only Kubernetes access. Retry only with the same journal and exact
source identity: an unknown POST result is recovered by exact list/GET and
Kubernetes ownership reads without reposting. A confirmed 401/403 admission
rejection clears the pending create only after a fresh list shows no logical
Namespace. Keep `activationEnabled: false` during rollback; preserve the
journal and add a reviewed repository-owned deletion path before removing the
logical Namespace. Never delete the pre-existing physical `openclaw-agents`
Namespace to undo this step.

Use these actual upstream operations:

| Purpose | Supported operation and invariant |
| --- | --- |
| Installation | `GET /installation` for identity/capabilities only; selected Driver comparison requires separate reviewed proof before mutation |
| Namespace | `GET/POST /namespaces`; create `name: claw`, `existingNamespace: openclaw-agents` only after prepared namespace/RBAC are ready |
| Secrets | Namespace Secret collection GET/POST; values supplied from an SSM-versioned 0600 private file, never echoed; changed versions block until reviewed rotation |
| Configuration | Namespace Configuration POST and exact GET/PATCH; updates use `expectedGeneration`, replacing the complete desired `values` |
| Agent | Agent collection/exact GET, POST create and PATCH `harnessAuth`; bind only one logical Claw |
| Runtime transport | `POST /namespaces/:ns/agents/:agent/runtime-credentials`; track its resulting state |
| Deploy | `POST /namespaces/:ns/agents/:agent/deploy`; persist returned revision; paginate revision history and inspect exact deployment before retry |
| Stop | `POST /namespaces/:ns/agents/:agent/stop`; require `operate`, preserve revision/state, verify stopped desired state, API runtime termination and an unfiltered empty tenant Pod list |
| Native UI | `GET /namespaces/:ns/agents/:agent/native-admin` requires a human session with exact Agent `administer`; service keys cannot inspect it. T048 records returned `data.origin` through authenticated human-session acceptance, outside the service-key reconciler. |
| IAM | Exact role/grant tuples; agent ServicePrincipal gets `operate` on its own model Secret, never installation administration |

The repository reconciler runs serially and stores server IDs/generations in a
protected durable journal. Discover before create. Configuration creation has no
list endpoint or caller-supplied idempotency key; an uncertain response stops
creation. Recover the ID from exact owned ConfigMap/audit metadata and confirm it
through API GET before journal adoption. Ambiguous or foreign candidates fail.
After a lost deploy response, inspect matching revisions before deploying again.
Do not use the Dedicated-only provisioning endpoint for Embedded.

The protected model-credential file is JSON with exactly `parameter`, `version`
and `key`: parameter must equal
`/homelab/openclaw-enterprise/model-api-key`, version is the positive SSM
parameter version, and key differs from the bootstrap service key. The
reconciler checks the file and parent modes, never stores a key or key digest
in its journal, and rejects a changed version until a separate rotation path
is reviewed. An uncertain Secret create is recovered only by a unique
journaled name, collection read and exact metadata; an uncertain deploy is
recovered only from complete paginated revision history and exact revision
readback. Neither response triggers a blind duplicate POST. Stop is a
separate exact-main command for a journaled revision; an Agent with no
journaled revision cannot prove an untracked runtime absent. A 202 is pending
work, not termination proof.

Test duplicate names, foreign ownership, changed input on retry, lost responses,
worker restart, generation conflicts, permission revocation and partial grants.
A second run must preserve the same IDs and grants without redeployment unless
configuration actually changed.

The pinned native-admin status handler returns `data.origin` with a derived
target even when the first active revision reports `unsupported` because its
native UI is disabled. An authorized owner must review that non-secret value
and commit it as `privateOrigins.nativeOrigin`. The accepted shape is the exact
`https://agent-<32 lowercase hex>.agents.oce.stinkyboi.com` origin, with its
host hash bound to the journaled Installation, Namespace, and Agent IDs. Final
automated active reconciliation and verification remain blocked while it is
`null`.
The source-only reconciler checks the first running revision and grants, then
CAS-updates the saved Configuration from generation 1 to 2. It journals the
first revision before admitting one second revision. Lost deployment responses
are recovered only from one exact new revision at the reviewed Configuration
generation; an absent or foreign result blocks reposting. Read-only verify
checks both immutable revisions and the selected second deployment without
sending inference. T041 remains open for protected live proof. The GitHub
runner also lacks a declared persistent
`/private/openclaw-enterprise/journal.json` volume; T043 keeps reconcile and
recovery stages disabled until an in-cluster durable mount is declared and
verified. The separate full-sync stage uses no journal and requires a reviewed
installation phase before Argo can sync. The source-built `occ` CLI digest is
pinned under T004; this reconciler uses the pinned public HTTP Agent routes and
never executes an ambient binary.

Pinned source: [first-Agent Configuration builder](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/scripts/first-agent.mjs),
[Agent create/deploy/stop API](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/reference/agents.md),
[route schemas](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/packages/contracts/src/api/routes.ts),
[native-admin host derivation](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/apps/controller/src/gateway/native-admin-host.mjs),
[native-admin human-session and response handler](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/apps/controller/src/http/native-admin.ts),
and [native-admin operator contract](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/reference/agent-native-admin.md).

## Installation and Upgrades

Foundation prerequisites must already exist before Enterprise PreSync: database
roles/TLS, bootstrap volume, secret references, immutable candidate installation
inputs, scoped namespace permissions and private routing. Initial root setup may
register everything together, but bounded hooks must wait for actual readiness.

Use only `helm.sh/hook: pre-install,pre-upgrade` annotations within this Application;
Argo maps Helm weights into its hook ordering. Do not mix native Argo hooks with
upstream Helm hooks. Do not rely on `.Release.IsUpgrade` under Argo rendering.

| Weight | Action |
| ---: | --- |
| -40 | Repository hook SA, scoped Role/Binding, NetworkPolicy, preflight ConfigMap |
| -30 | Upstream bootstrap NetworkPolicy |
| -20 | Upstream initialization ServiceAccount |
| -18 | Repository preflight with candidate image and checksum-pinned upstream `check-installation.mjs`; dependency/secret/storage checks |
| -15 | Repository quiesce Job validates exact API/worker ownership and scales only those two Deployments to zero; waits for all matching Pods to terminate |
| -10 | Unmodified upstream initialization: migrate, then bootstrap |
| Normal Sync | Stock API/worker Deployments resume at one replica |

The preflight script is chart content, not present in the controller image; mount
its exact pinned bytes. Its scope is Installation configuration, not a substitute
for database/readiness checks. Version candidate startup inputs so preflight failure
cannot alter the running installation's configuration.

Quiesce permissions: named Deployment get, named `deployments/scale` get/update,
namespaced Pod get/list; no Pod delete or cluster-admin. Require replicas in `{0,1}`,
release/component identity, and no matching Pods after scaling. First-install
absence is valid only when both Deployments are absent. Unknown node/writer state
or partial ownership blocks migration. A previous initialization Job and its Pods
must be terminal before a retry can start another one.

Set inherited `selfHeal` false; disallow autoscalers, independent writers,
selective sync, skip-hook operations, and `ApplyOutOfSyncOnly`. Serialize full
release syncs. A source change can still trigger multi-source autosync, so every
sync must execute these gates. Disable automated sync declaratively during any
recovery window spanning multiple operations.

Test on the installed Argo version: empty install, invalid preflight leaving old
writers running, failed quiescence blocking migration, failed migration leaving
writers stopped, cancellation/restart, retry without concurrent Jobs, and successful
normal Sync restoring replicas after scale-subresource updates. Do not enable
production until this ordering is observed, including failure paths.

Sources: [Argo Helm hooks](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/#helm-hooks),
[autosync](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/),
[upstream chart](https://github.com/openclaw/openclaw-enterprise/tree/33bb74590a749f37934da4502fca6035cd234a55/deploy/helm/openclaw-enterprise).

## Gateway API and Private Envoy

The platform Envoy Application is the single shared CRD owner. Render pinned
`gateway-crds-helm` v1.9.2 with `crds.gatewayAPI.enabled: true`,
`crds.gatewayAPI.channel: experimental`, and `crds.envoyGateway.enabled: true`.
Require Gateway API bundle v1.6.1. Render `gateway-helm` v1.9.2 with
`crds.enabled: false`; apply CRDs before controllers through Argo's declared
server-side apply path. Keep safe-upgrade admission resources under that same
owner. Do not prune/downgrade shared CRDs with Enterprise retirement.

Verify Gateway/HTTPRoute v1, EnvoyProxy/SecurityPolicy v1alpha1 and cert-manager
v1 discovery before OCE initialization. Also verify Istio's TCPRoute/UDPRoute
v1alpha2 and ReferenceGrant v1beta1 watches remain available; check both controller
logs and rendered routes. Future served/storage-version changes require a separate
migration review.

Set `gatewayRouting.gatewayName: oce-private-gateway`. The final local Argo source
overrides exactly the upstream-rendered EnvoyProxy with that name in
`openclaw-system`. Preserve all rendered labels, provider fields, generated
service name, ClusterIP type and node placement; add the Harbor digest for Envoy
`distroless-v1.39.3` at
`spec.provider.kubernetes.envoyDeployment.container.image`. No behavior fork or
global-default assumption. Assert the effective merged object differs only by
this image field; require exactly this one expected `RepeatedResourceWarning`
and reject every other duplicate. Recheck the assertion on chart upgrades.

Observe the actual proxy Deployment image digest, Accepted/Programmed conditions,
listener/routes and absence of xDS rejections, then test routing after a cold
proxy restart. Healthy controller Pods alone do not prove the data plane.

Sources: [CRD values](https://github.com/envoyproxy/gateway/blob/v1.9.2/charts/gateway-crds-helm/values.yaml),
[controller CRD switch](https://github.com/envoyproxy/gateway/blob/v1.9.2/charts/gateway-helm/values.tmpl.yaml),
[image pinning and security fix](https://gateway.envoyproxy.io/news/releases/notes/v1.9.2/),
[Argo override semantics](https://argo-cd.readthedocs.io/en/stable/user-guide/multiple_sources/).

## Access and Secret Boundaries

| Contract | Consumer and restriction |
| --- | --- |
| PostgreSQL admin password | Database administration/bootstrap only |
| `occ_migrator` password | Migration Job only; owns required schemas, no superuser/role creation |
| `occ_app` password | API/worker; no CREATE privilege or migrator inheritance |
| Session auth secret | OCE auth components; stable and included in recovery |
| Private gateway key and CA | Exact control-plane/private-routing consumers |
| Bootstrap admin password/service key | Private bootstrap output and authorized reconciliation only; never agent-mounted |
| `/homelab/openclaw-enterprise/model-api-key` | New external credential contract, projected only to the intended fresh agent |

Declare exact producer/reader/ExternalSecret/target/key/consumer/refresh contracts
through existing SSM/ESO ownership. Prefer file inputs where upstream supports
them. OCE's native agent secret delivery uses controller-managed environment
projection; document that specific runtime limitation, keep values out of source,
and never use operator-exported variables as desired state. No old Discord,
LiteLLM, GitHub, hook, signing, or account credentials enter the new installation.

Use native password/session IAM behind Octelium. Console is
`https://console.oce.stinkyboi.com`; native agents use the exact returned origin
under `agents.oce.stinkyboi.com`; session cookie scope is `oce.stinkyboi.com`.
The old URL redirects after authentication. Preserve Host/WebSocket and only trust
exact declared proxy sources; strip untrusted forwarded headers.

Both browser paths terminate at OCE API, which checks exact-agent permission
before forwarding through private Envoy. No direct browser route to private Envoy
or the gateway. Private DNS and browser-trusted certificates must be verified
end-to-end; do not publish wildcard ingress to make an origin resolve.

The stock chart renders destination-free TCP 5432 and 443 egress when
`database.cidrs` or `cluster.cidrs` is empty. Kubernetes treats an empty `to`
field as all destinations. Supply reviewed nonempty lists, assert the rendered
policy, and qualify Service DNAT behavior on the Talos canary before install.

## Legacy Shutdown and New Recovery

1. Inventory the old image/config, local database and NAS roots, PV/PVC identities,
   archive sizes/hashes/permissions, and retained historical checkpoints privately.
2. Declare old gateway replicas zero and suspend its scheduled writers through
   GitOps. Wait for termination; do not force-delete an uncertain writer.
3. Take the final complete offline archive, explicitly including local DB mounts
   and NAS files. Verify database integrity and restore an independent copy.
4. Keep the old claims and archived credentials private. New Enterprise receives
   fresh state. Stopping the old runtime disables its Discord/heartbeat/job delivery.
5. After new acceptance and 24h observation, retire obsolete active resources via
   the existing protected retirement path. Check Argo finalizers/prune behavior;
   retain storage before deleting old Application resources.
6. On failure, stop the new agent through OCE's supported lifecycle while its
   control plane remains available. Confirm stopped desired state and zero
   gateway/harness Pods with no uncertain node/writer. Then quiesce API/worker
   through GitOps, preserve new database/agent/recovery state, and restore the
   old compatible instance if needed. If the control plane is unavailable or
   runtime termination cannot be verified, stop recovery for the declared
   disaster-recovery path; scaling API/worker alone does not stop agents.
   Never combine databases or replay old delivered jobs into the fresh instance.

Planned retirement helper operations: read-only `inventory` and `verify-archive`,
plus workflow-only `archive` against stopped, identity-checked sources. It accepts
committed config and private output paths, refuses active/unexpected sources,
and publishes a completion marker only after full verification. Missing optional
already-retired resources are idempotent success; missing required data is failure.

New recovery sets cover PostgreSQL, tenant metadata/secrets, agent state, bootstrap
output, auth secret, and private gateway identity. Require real isolated restore,
not merely `pg_restore --list`. OCE agent deletion may delete its claim; retain
explicitly before deletion. Data disposal remains separately authorized.

Test rollback ordering and interrupted agent shutdown. No legacy restoration or
enforcement removal proceeds while a new agent may still run.
