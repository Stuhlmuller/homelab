# LiteLLM gateway

LiteLLM is the internal OpenAI-compatible gateway for OpenClaw, Multica, n8n
and NOFX. It exposes only `openrouter/free`.

The existing `/homelab/litellm/openai-api-key` SSM SecureString is the
OpenRouter upstream credential for this gateway. Its legacy name is retained to
avoid a secret-path migration. It seeds the encrypted UI credential once and
remains mounted only in LiteLLM for initial bootstrap; callers authenticate
with separate inference-only keys:

- `/homelab/openclaw/litellm-app-token`
- `/homelab/multica/litellm-token`
- `/homelab/nofx/litellm-token`
- `/homelab/n8n/litellm-token`

The guarded ASGI entrypoint rejects caller-controlled provider credentials,
routing and telemetry before native authentication. It rejects callbacks
and telemetry configuration; injects the upstream credential only in memory;
and emits trusted caller attribution to Langfuse. Raw request logging is
disabled. The Langfuse keys are mounted only in LiteLLM.

## Validation and rollout

### October 10, 2026 native-key rollout

[PR #1243](https://github.com/Stuhlmuller/homelab/pull/1243) merged as
`998041ea` after all protected checks passed. Argo observed that revision with
Synced/Healthy and a successful operation. The new gateway pod became Ready
without restarts; PostgreSQL contains the native schema, import marker and four
service-key rows. The native UI key-list API returns `openclaw`, `multica`,
`nofx` and `n8n`. Each caller's own running pod authenticated to
`http://litellm.ai.svc.cluster.local:4000/v1/models` with its configured key and
received only `openrouter/free`.

A disposable ten-minute key passed creation, authentication, block, unblock
and deletion checks through the native API. Block and delete invalidated its
warm authentication cache. The test key was deleted; service keys were not
modified. Langfuse's repaired Valkey AOF loaded after the reviewed restart on
October 10. Fresh bounded requests using each of the four mounted service keys
produced attributed Langfuse `GENERATION`s through `openrouter/free`, with
input/output and nonzero usage. The n8n key's first free-model response had no
assistant text; a second returned `READY` and was traced. Browser UI rendering,
native post-recovery caller actions, and a database restore drill remain
unverified. Model discovery alone is not completion.

### Native database-backed service keys

The dedicated `litellm-postgres` StatefulSet stores UI-visible virtual keys.
The gateway reads its nonsuperuser database password from a mounted file and
creates a private temporary native config before CLI initialization. Native
LiteLLM applies its pinned schema migrations. Before accepting HTTP traffic,
`native_keys.py` imports the four existing SSM caller values as hashed native
keys and creates their internal-user records in one locked transaction.
Clients need no key rotation. Each key permits only model discovery and free
chat completions, including both versioned and unversioned paths.

The `homelab-native-key-import-v1` user record marks completed import in the
same transaction. Once present, startup never recreates keys or restores old
permissions. UI deletion, blocking and rotation remain authoritative across
restarts. Do not delete this marker. An existing user/key collision aborts
startup rather than overwriting operator state. No custom-auth hook remains:
the native database verifier authorizes requests, while ASGI admission blocks
provider and telemetry overrides before native error logging can parse them.
Only the trusted pre-call hook inserts the database-backed upstream credential.
Telemetry admission covers management and model-discovery routes too: native
authentication failures can parse their bodies before logging. Model/provider
restrictions apply only to inference, preserving native key-management bodies.

The pinned image is affected by
[GHSA-4xpc-pv4p-pm3w](https://github.com/BerriAI/litellm/security/advisories/GHSA-4xpc-pv4p-pm3w).
Admission rejects malformed or duplicate Host headers on every HTTP route
before native authentication, including direct ClusterIP access. Tests pin the
deployed FastAPI/Starlette versions: the unguarded management route reproduces
the bypass and the guarded route rejects it. Keep this mitigation until an
image upgrade and its regression tests establish the upstream fix; a newer
implicit test dependency is not evidence that the deployed image is safe.

SSM provides initial caller material, not a continuous key reconciliation
loop. After import, changing SSM alone does not rotate a database key. Coordinate
any later UI/API rotation with that caller's SSM value and refresh contract.

### UI-managed OpenRouter credential

`native_keys.py` imports the existing OpenRouter value into native
`LiteLLM_CredentialsTable` as `openrouter`, encrypted with LiteLLM's native
encryption helper. Its independent `homelab-provider-credential-import-v1`
marker commits in the same locked transaction. Existing credential collisions
abort startup; completed imports never overwrite UI edits or recreate deletion.
The four caller keys stay under **Virtual Keys**; OpenRouter appears under
**Models → LLM Credentials**. The bootstrap master key and PostgreSQL/Langfuse
credentials retain their separate administrative and infrastructure roles.

The pre-call hook reads and decrypts only this row's `api_key` on each request.
UI replacement/deletion affects subsequent requests without restarting; missing,
invalid or unreadable credentials return 503 with no mounted-secret fallback.
Inference admission also rejects `litellm_credential_name` overrides. Native
`store_model_in_db` enables the UI credential loader and its 30-second refresh;
the gateway loads credentials again after first import, before serving traffic.
`supported_db_objects: []` keeps models and other routing objects in Git.
The inference model remains restricted to `openrouter/free`.

After migration, change the provider credential in the UI/API. Updating SSM
alone no longer rotates the active provider key. Keep SSM as bootstrap/recovery
material and preserve the database plus import markers. The existing master key
is the native encryption key because no separate salt is configured: retain it
with database backups, and do not rotate it without re-encrypting stored values.
Never return to file-backed inference during rollback; restore the database.

Pinned 1.80.8 UI limitation: editing a credential preloads a masked value. Enter
the complete replacement key before saving; saving that mask can overwrite the
credential. Review the upstream credential edit flow during the next image
upgrade. Native stdout/client errors also remain outside the existing Langfuse
redaction guarantee; see the [AI observability findings](../../../../openwiki/architecture/ai-observability.md).

Before rollout, capture a private logical backup. After rollout, require the
`openrouter` entry from `/credentials`, one encrypted database row, unchanged
caller aliases, and a bounded real generation. Local database tests cover
encryption, concurrent import, collision rollback, UI rotation/deletion,
restart preservation and unavailable-credential failure without using live keys.

PostgreSQL reuses the mirrored PostgreSQL 14 image and a 20 GiB `nfs-default`
claim, `data-litellm-postgres-0`. Generated SSM credentials are
`/homelab/litellm/postgres-admin-password` and
`/homelab/litellm/postgres-app-password`. Only PostgreSQL receives the admin
password; `litellm-postgres-client` contains only the app password. The init
script creates the nonsuperuser `litellm` role and owned database on an empty
volume. Network and Istio policies admit port 5432 only from LiteLLM.
Both policies use sync wave `-1`, before PostgreSQL's wave `0`: unavailable
Istio admission must block initial database deployment, not leave policy
installation racing the database startup.

PR #1230 merged as `201e0988`. Its reviewed SSM plan was applied and the
database reached Ready with a Bound PVC and both ExternalSecrets Ready.
On October 10, 2026, the Istio webhook outage exhausted Argo's retries before
the database AuthorizationPolicy was created. The worker and `istiod` later
recovered; this ordering correction supplies a new reviewed revision for
normal automatic reconciliation. Require Synced/Healthy, a successful sync,
and the policy present before native-key migration. Do not bypass admission.

The Application enables
[server-side diff](https://argo-cd.readthedocs.io/en/stable/user-guide/diff-strategies/)
through `IaC/stacks/litellm/stack.hcl`. Argo's older structured-merge comparison
reported the Ready PostgreSQL StatefulSet OutOfSync while both the normal CLI
diff and Kubernetes server-side dry run were empty (including Argo tracking
metadata). This setting uses admission-aware dry runs without ignoring fields
or changing database resources. Apply the reviewed registration with the
targeted `litellm` Terragrunt workflow; require actual Synced/Healthy afterward.

On October 10, 2026, PR #1244 merged as `058fec59`; targeted apply
[38082662328](https://github.com/Stuhlmuller/homelab/actions/runs/38082662328)
succeeded and the live Application has `ServerSideDiff=true`. PostgreSQL and
its PVC/secrets remain Ready/Bound. The first post-apply comparison still
reported the previous OutOfSync result.
[Argo 3.4.2 cache selection](https://github.com/argoproj/argo-cd/blob/v3.4.2/controller/state.go#L1036-L1072)
does not invalidate cached diffs for this metadata-only change, and server-side
diff keeps that cache across ordinary status expiration. A new source revision
invalidates it. Verify the next observed Git revision and fresh Synced/Healthy
result before the native-key cutover; do not treat successful apply alone as
convergence or bypass it with an ignored-field rule.

Provision these parameters and exact reader grants through the reviewed shared
SSM Terragrunt unit before acceptance. Require both ExternalSecrets Ready, the
claim Bound, StatefulSet Ready and `SELECT 1` as the app role. Passwords are
file-backed. SSM rotation alone does not change an initialized PostgreSQL role;
use a reviewed role-password migration before changing mounts.

Before schema upgrades or auth cutover, keep a private logical `pg_dump` of
database `litellm` alongside its NFS snapshot and SSM recovery material. Restore
the database before restoring database-backed authentication; retain its PVC
during rollback. Returning to file-backed authentication would ignore UI
revocations and must not be an automatic recovery action.

Validate with `scripts/ci/litellm-postgres-check.py`, the pinned SDK
`litellm-attribution-check.py` and `litellm-native-auth-test.py`, plus
`litellm-native-database-test.py` under the Nix shell with the generated Prisma
0.11.0 client. The database test uses isolated local PostgreSQL, the pinned
native migrations, and a nonsuperuser owner. It proves atomic concurrent import,
rollback on collision, and preservation of deleted/blocked keys after restart.
CI runs these without production credentials.

Before rollout, take the private logical backup described above and verify the
database policies, Ready Secret/PVC and app-role connection. After rollout,
require four aliases (`openclaw`, `multica`, `nofx`, `n8n`) in the UI and test a
separate disposable key through UI/API create, authenticate, block and delete.
Prove cache invalidation and restart preservation, then each native caller's
inference and correlated Langfuse generation. Local fixtures do not prove these
live acceptance gates. Never roll back to file-only authentication: that would
silently ignore database revocations. Preserve the database and import marker.

Run:

```sh
nix develop --command python3 -I scripts/ci/langfuse-staging-check.py
nix develop --command python3 -I scripts/ci/litellm-attribution-check.py
kubectl kustomize clusters/homelab/apps/litellm
```

Before acceptance, make one bounded generation per migrated caller and verify a
correlated Langfuse generation has the caller identity, `openrouter/free`,
input/output and nonzero provider usage. Gateway health and a Ready
ExternalSecret are not acceptance evidence.

NOFX uses a separately pinned image containing
`builds/nofx/patches/0013-litellm-runtime-routing.patch` and mounts its gateway
route and dedicated token only in the backend.

Sources: [LiteLLM custom authentication](https://docs.litellm.ai/docs/proxy/custom_auth),
[Langfuse LiteLLM integration](https://langfuse.com/integrations/gateways/litellm).
