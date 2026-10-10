# LiteLLM gateway

LiteLLM is the internal OpenAI-compatible gateway for OpenClaw, Multica, and
NOFX. It exposes only `openrouter/free`.

The existing `/homelab/litellm/openai-api-key` SSM SecureString is the
OpenRouter upstream credential for this gateway. Its legacy name is retained to
avoid a secret migration. It is mounted only in LiteLLM; callers authenticate
with separate inference-only keys:

- `/homelab/openclaw/litellm-app-token`
- `/homelab/multica/litellm-token`
- `/homelab/nofx/litellm-token`
- `/homelab/n8n/litellm-token`

The guarded ASGI entrypoint authenticates the caller before LiteLLM processes a
request. It rejects caller-controlled provider credentials, routing, callbacks
and telemetry configuration; injects the upstream credential only in memory;
and emits trusted caller attribution to Langfuse. Raw request logging is
disabled. The Langfuse keys are mounted only in LiteLLM.

## Validation and rollout

### Database-key migration prerequisite

The dedicated `litellm-postgres` StatefulSet prepares persistent storage for
UI-visible virtual keys. This prerequisite does **not** change authentication
or import keys yet; the gateway remains on existing file-backed keys until
database readiness and the separate native-auth cutover are validated.
Import the existing SSM caller values so clients need no key rotation.

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

Validate with
`nix develop --command python3 -I scripts/ci/litellm-postgres-check.py`.

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
