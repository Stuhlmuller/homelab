---
type: architecture
title: "AI observability"
description: "LiteLLM caller routing, OpenRouter credentials, Langfuse attribution, and per-caller telemetry acceptance gates."
tags: ["homelab", "navigation"]
---

# AI observability

Langfuse is the operator UI for prompts, outputs, errors and token usage.
LiteLLM is the sole in-cluster inference gateway: it accepts only
`openrouter/free`, authenticates named callers with dedicated keys and emits
trusted application attribution to Langfuse. The provider credential is mounted
only by LiteLLM from `/homelab/litellm/openai-api-key`; it is an OpenRouter
credential despite the legacy SSM parameter name.

The gateway rejects request-supplied callback, tracing and credential overrides
before LiteLLM parses them. Langfuse credentials are file-mounted, never passed
by callers. See the [gateway contract](../../clusters/homelab/apps/litellm/README.md).

## Caller inventory

### UI-visible key migration (native cutover awaiting deployment)

The operator requested database-backed keys visible in LiteLLM's UI. The first
prerequisite added dedicated PostgreSQL storage and separate generated admin/app
SSM credentials, reusing existing NFS and PostgreSQL patterns. The native cutover
imports existing caller values in one transaction with a durable import marker,
so restarts do not undo UI revocations. It uses database authentication, preserves
inference-only/free-model restrictions and Langfuse attribution. Still prove UI
listing plus revocation enforcement. Copying rows into the UI while retaining
file-based authentication is not completion. See the
[gateway runbook](../../clusters/homelab/apps/litellm/README.md).

October 10 security gate: the pinned LiteLLM 1.80.8 is within the affected
range (`<1.84.0`) of
[GHSA-4xpc-pv4p-pm3w](https://github.com/BerriAI/litellm/security/advisories/GHSA-4xpc-pv4p-pm3w).
A crafted Host header can make native authentication evaluate a different
route from FastAPI. The prepared ASGI guard now rejects malformed and duplicate
Host headers before native authentication on all HTTP routes. The regression
pins the live image's FastAPI 0.120.1 and Starlette 0.49.1, reproduces an
unauthenticated management-route bypass without admission, and rejects it with
admission. Local auth and attribution tests pass; the mitigation is not yet
deployed or verified through the live internal service. The local environment
previously resolved a newer Starlette with a fixed parser, hiding this exposure.
Keep the guard until a reviewed image upgrade establishes the upstream fix.
The separately inspected
[salt-key advisory](https://github.com/BerriAI/litellm/security/advisories/GHSA-7hp6-4w63-5g45)
does not include 1.80.8 in its affected ranges.

The synthetic streaming failure fixture also exposed native Router logs
echoing a synthetic provider credential embedded in upstream error text.
Langfuse redaction does not protect native stdout. No production credential
was used in this fixture. Add and test credential redaction for native error
logs, and inspect client error responses, before claiming end-to-end secret
redaction.

On October 10, PR #1230's SSM credentials and PostgreSQL were provisioned;
the app role passed local-socket `SELECT 1` and remained a nonsuperuser.
An outage of `zimaboard-1` removed Istio's admission endpoint. Argo exhausted
its retries and the database AuthorizationPolicy remained absent, even after
the worker and `istiod` recovered. Both database access policies now precede
PostgreSQL in sync wave `-1`, so future initial deployments stop at admission
failure before starting the database. This correction requires protected merge
and automatic reconciliation; no live policy bypass or node changes were made.
Keep native authentication, UI listing and revocation marked unverified until
the separate key migration and its live acceptance finish.

Pre-cutover inspection found zero public tables in the live `litellm` database
and confirmed its owner is not a superuser. A private off-NAS custom-format
`pg_dump` was captured and its archive table of contents verified before any
native schema migration. This is a readable logical backup, not a completed
restore drill. The local PostgreSQL fixture passed the pinned native migrations,
concurrent atomic import, collision rollback and preservation of revocations.

PR #1238 merged as `cecd243f`; Argo observed that revision and its operation
succeeded. The database AuthorizationPolicy is now present at wave `-1` with
the exact LiteLLM principal and port 5432. PostgreSQL remains Ready. Argo still
reports its StatefulSet OutOfSync although `kubectl diff` is empty; inspect
Argo's normalized comparison before declaring full convergence. No PVC was
replaced and no live force-sync was used.

Follow-up read-only inspection found no diff through the controller's native
`argocd app diff --core`. A Kubernetes server-side dry run using field manager
`argocd-controller` also found no change after including Argo's generated
tracking annotation. PostgreSQL's current/update revisions match, its replica
is Ready, and both database ExternalSecrets are Ready. Argo's OutOfSync status
remains unexplained; no ignore rule, force-sync or live repair was introduced.

The `litellm-app-keys` revision `v2` refreshes the file-mounted OpenRouter
credential after protected SSM injection. Merge this refresh only after the
provider credential workflow succeeds. The gateway rereads the mounted key for
each request; no manual restart is required. Verify a real gateway generation
and its Langfuse trace before claiming recovery. Explicit remote-reference
defaults match the External Secrets API to prevent persistent Argo drift.

| Caller | Gateway identity | State |
| --- | --- | --- |
| OpenClaw | `/homelab/openclaw/litellm-app-token` | Routed to `openrouter/free`; Codex subscription runtime removed. |
| Multica | `/homelab/multica/litellm-token` | OpenCode uses the internal gateway; Codex runtime removed. |
| NOFX | `/homelab/nofx/litellm-token` | Backend uses the internal gateway through a file-backed route and dedicated read-only token mount; its pinned image includes patch `0013`. |
| n8n | `/homelab/n8n/litellm-token` | Secret-backed OpenAI credential override targets LiteLLM. The idempotent CLI migration keeps its credential and target-workflow exports as n8n's one-element arrays, then replaces the exact Bedrock node with `openrouter/free`. The gateway key never enters workflow JSON. |

AFFiNE has no active AI workload. OctoBot's AI evaluators are disabled. Cordium
may host user workloads and remains outside this cluster-owned routing contract.

## Current rollout dependency

### October 10, 2026: Langfuse queue recovery

#### Pre-repair state (historical)

Read-only follow-up found `langfuse-valkey` in CrashLoopBackOff and its worker
restarting. Valkey 8.0.11 loaded its base RDB, then rejected
`appendonly.aof.4.incr.aof` as malformed. The PVC `langfuse-valkey-data` is
retained; at this stage no files had been removed or repaired. Trace acceptance
was blocked even though the web Pod was Ready. The repair required a private
backup, a reviewed repository-owned recovery path, and approval for possible
loss of queued events after the corruption point. Acceptance also required
stable Valkey/worker readiness and a fresh correlated generation per caller.
The [copy-only inspection helper](../../scripts/langfuse-valkey-recovery.py)
preserves a verified original and repairs only a private candidate. Its safety
tests include a synthetic corrupt tail checked with native Valkey 8.0.11.
The authorized capture stage stopped web/worker/Valkey through GitOps and mounted
the queue read-only in a credential-free inspector. The helper verified all
writers exited before capture to private off-NAS storage. No live replacement
path was activated at this stage; see the [recovery runbook](../../clusters/homelab/apps/langfuse/README.md#valkey-offline-capture-and-candidate-inspection).

[PR #1240](https://github.com/Stuhlmuller/homelab/pull/1240) merged as verified
`fe1838c49eaa11897f5d7f375eae94ba439e3f4f`. Argo observed that revision and
finished Synced/Healthy; all three writer Pods exited, the read-only inspector
became Ready, and PostgreSQL/ClickHouse remained Ready. Full static validation,
26,152 rendered policy checks and all required CI gates passed.
The private off-NAS archive passed SHA-256 verification. Native Valkey 8.0.11
validated the repaired candidate: only `appendonly.aof.4.incr.aof` changed,
from 10,328,329 to 9,987,809 bytes, discarding 340,520 bytes. Original source
and backup hashes stayed unchanged. This measures bytes, not lost events, and
does not prove runtime loading or fresh ingestion. Langfuse remained
intentionally offline pending approved replacement and a repository-owned
restart. LiteLLM native/UI-visible key migration had completed, but live
trace acceptance was still pending at this stage.

#### Recovery and verification

Subsequent October 10 approval explicitly permits the 340,520-byte truncation
and restart while retaining the off-NAS original. The prepared promotion path
keeps all writers stopped, changes only the inspector's PVC mount to writable,
verifies archive/original/candidate integrity and exact live hashes, and stages
then atomically replaces only the approved incremental AOF. The approved
candidate was promoted and exact live hashes verified. A reviewed GitOps change
removed the inspector first, with writers still stopped. Argo observed merged
`836e7f0f`, pruned the inspector and reported Synced/Healthy; no Pod mounted
its PVC. PR #1261 merged as verified `ee807517` and restored all three
writers. Valkey loaded its base RDB and repaired incremental AOF without a
corruption error or restart; web and worker reached 1/1 Ready, and Langfuse
reported Synced/Healthy at that revision.

Fresh bounded gateway requests authenticated with each dedicated mounted key.
Langfuse v2 observations recorded `GENERATION`s with the matching input marker,
`openrouter/free` route, caller identity, output and nonzero usage:

| Caller | Observation | Tokens |
| --- | --- | ---: |
| OpenClaw | `e8eff862d6c4b2e7` | 86 |
| Multica | `41fc201db4cdb962` | 83 |
| n8n | `8c3a6a7fa7c8cff7` | 173 |
| NOFX | `1bb76f16d66e0f38` | 75 |

The first n8n request resolved to a free content-safety model and returned no
assistant text; the second returned `READY` and is the observation above. These
are direct gateway requests with each service key, not native app actions.
Live n8n database inspection found all three inventoried model nodes targeting
`openrouter/free` and `litellm-managed`; its two inactive workflows stayed
inactive. OpenClaw's live default and allowed model are `openrouter/free`, with
no active auth profiles and both Codex/OpenAI plugins disabled. Native
post-recovery app actions, visual UI key listing, and an independent datastore
restore drill remain unverified.

During the final rollout check, `zimaboard-2` became unreachable and its
terminating `n8n-postgres-0` left n8n at 0/1 Ready even though both Argo
Applications reported Synced/Healthy. Kubernetes recreated PostgreSQL on
`zimaboard-0` after the node returned; PostgreSQL and n8n then reached 1/1
without manual mutation. Keep workload readiness in release checks rather than
using Argo health alone for this dependency chain.
LiteLLM's later native-key rollout is now recorded in its
[owning runbook](../../clusters/homelab/apps/litellm/README.md#october-10-2026-native-key-rollout).

Native-key cutover inspection confirmed all four mounted caller credentials
already use the `sk-` format required by pinned LiteLLM 1.80.8. Its
`GenerateKeyRequest.key` accepts an existing value, so import need not rotate
clients. Its custom-auth branch returns before database key verification;
adding database rows alone would not enforce UI revocation. The new
`scripts/ci/litellm-native-auth-test.py` exercises the actual pinned native
authentication dependency with an in-memory store: existing keys authenticate;
blocked/deleted keys, disallowed models and management routes are denied.
Allowed routes must include both versioned and unversioned paths. This does
not test a live database, UI mutation or cache invalidation. Database connection,
one-time import and removal of the custom-auth bypass remain required before
claiming migration; retain pre-auth telemetry admission and provider controls.

An earlier ClickHouse logging change exposed a sync-wave dependency: its
generated ConfigMap followed the Deployment, so Argo waited for a Pod that
could not mount its configuration. [PR #1167](https://github.com/Stuhlmuller/homelab/pull/1167)
fixed the ordering. That logging override has since been removed; keep future
generated configuration ahead of its consumers. An existing sync can hold an
older revision until the declared 900-second controller timeout releases it.
See [GitOps Flow](gitops-flow.md) and Argo CD's
[timeout handling](https://github.com/argoproj/argo-cd/blob/v3.4.2/controller/appcontroller.go#L1454-L1465).

## Acceptance

### Follow-up verification, October 6, 2026 PDT

Live OpenClaw configuration now contains only the provider targeting
`http://litellm.ai.svc.cluster.local:4000/v1`, default `openrouter/free`, no
fallbacks or active auth profiles, and disabled OpenAI/Codex plugins. OpenClaw,
LiteLLM, Multica, n8n, NOFX and Langfuse Applications report Synced/Healthy.
These checks establish configuration and readiness, not inference acceptance.

The isolated installed n8n `LmChatOpenAi` node completed a fresh request without
executing downstream workflow actions. Langfuse generation `a82fef8bb18694a3`,
trace `0640a8d5deac6725d1b702d25cc9c151`, matched marker
`homelab-n8n-native-node-20261006`, identity `n8n`, output, and 244 tokens
(43 input, 201 output). OpenRouter resolved the free alias to
`nvidia/nemotron-3-super-120b-a12b:free`. Its timestamp is October 7 UTC;
the first immediate query was empty and the subsequent query found the event.
This closes native-node inference and tracing acceptance, not a full workflow
execution.

A fresh real OpenClaw agent turn returned `4` through `openrouter/free` without
fallback. Langfuse generation `4fe660e4218bbdd7`, trace
`6e7258a4f9893cce75ea36773559f639`, matched marker
`homelab-openclaw-generation-20261006`, identity `openclaw`, output and 42041
tokens (42039 input, 2 output). Generation typing is fixed, but its observation
model field is empty; inspect the streaming exporter before claiming complete
model visibility. A real SDK-span regression reproduced the cause: 47 tool
schemas exceed the default 128-attribute limit and evict the early model
attribute. The prepared callback revision 8 retains model identity after native
metadata expansion; it still needs protected delivery and live verification.
PR #1216 merged as `f7ddf33e76452716c24192175145f21ede2ee2f0`; GitOps
deployed callback revision 8. A fresh real OpenClaw turn produced generation
`67b9bc7760a75b0d`, trace `d1cadeb7dba7972fa54363db0fd53bbf`, with model
`openrouter/free`, authenticated identity `openclaw`, matching marker
`homelab-openclaw-revision8-20261006`, output, and 43007 tokens (42980 input,
27 output). The native agent confirmed no fallback. This verifies the model
retention correction live. NOFX's gateway-only image rollout remains unverified.

A fresh installed Multica OpenCode run also succeeded on revision 8. Generation
`054b15591f8c0ac1`, trace `3ad6047c4bb253380f478cda968dc0d1`, matched its
synthetic marker, identity `multica`, model `openrouter/free`, input/output and
7882 tokens. A second attributed generation used 833 tokens. Live config
enabled only `litellm`, with both model slots pointing to `litellm/openrouter/free`
and the API key referencing the mounted file. This remains installed-client
acceptance, not a backend-dispatched task.

Configuration is not acceptance. For each active caller, verify a real request
creates one Langfuse generation with its gateway app identity, `openrouter/free`,
input/output and provider token usage. Verify error traces do not expose bearer
credentials. A healthy Deployment, Argo sync or synthetic gateway test is not
enough.

On 2026-10-06 UTC, protected workflow run `37408906677` wrote SSM version 3;
the temporary GitHub credential was removed. PR #1199 deployed revision `v2`,
and LiteLLM became Synced/Healthy. A bounded HTTP smoke from the OpenClaw pod
using its dedicated key returned text through `openrouter/free` (HTTP 200).
Langfuse generation `a6a4ff345e23339a`, trace
`142c5a894eca6a1199b2e41f395356ba`, matched the synthetic input and output,
identity `openclaw`, and 155 tokens. The resolved provider model was
`inclusionai/ling-3.0-flash-sante:free`. This verifies the gateway credential
path, not a full OpenClaw agent turn or acceptance of the other callers.
This deployment uses Langfuse v4 events-only mode: use
`/api/public/v2/observations` with field groups `core,basic,model,usage,io`;
legacy traces/observations endpoints return 404. Ingestion was delayed.

Further verification on the same date: the deployed Multica OpenCode client
returned text through `litellm/openrouter/free`; generation `8bd8445cfd4767b4`
matched the test marker, identity `multica`, input/output and 7592 tokens.
This exercises the installed agent client, not Multica backend task dispatch.
A real OpenClaw gateway agent turn returned text with `openrouter/free`, no
tool calls, and 49720 tokens. Observation `2e79c0fc1c0a30df` in trace
`03b7bd8d4b6aeeefd2e70edc16c088af` matched its marker, input/output, identity
and usage, but Langfuse classified it as `SPAN`, not `GENERATION`. Inspect
streaming observation typing before claiming generation-level acceptance.
The n8n read-only CLI export hung and was terminated. A subsequent read-only
database inventory of all ten workflows confirmed the active model node uses
`openrouter/free` and `litellm-managed`. It also found two inactive workflows
still configured with `gpt-5.5` and AWS Bedrock Claude 3 Sonnet, respectively.
The prepared init migration now covers these three exact workflow/node IDs,
rejects changed model/options, and republishes only previously active workflows.
It awaits deployment; inactive workflows must remain inactive afterward.
The active error workflow includes HTTP actions and Discord
notifications; do not trigger it wholesale for an inference smoke check.
Bounded native-node acceptance and NOFX inference acceptance remain outstanding.

The isolated installed n8n model node failed with a connection error on
2026-10-06; a direct authenticated model-discovery request from the same pod
also ended with a socket close. Both namespaces use ambient mesh, and the
live LiteLLM AuthorizationPolicy omitted n8n's confirmed service account.
The prepared fix admits only `cluster.local/ns/automation/sa/n8n` on port 4000;
the n8n regression now checks that route. Re-test native-node inference and
Langfuse attribution after GitOps deployment; no workflow actions were run.

Gateway checks on 2026-10-06 confirmed five distinct, nonempty internal keys,
all different from the upstream credential. Each lists only `openrouter/free`;
missing/invalid keys return 401. All four app keys reject administration (403),
nonfree model requests (400), and caller-supplied provider credentials (400).
Multica's Ready gateway ExternalSecret still reports Argo drift; declare its
three remote-reference defaults explicitly, matching the converged LiteLLM
contract. This does not rotate its key or change its `OnChange` policy.

### NOFX credential contract mismatch

Read-only SQLite inspection found one enabled model (`openrouter/free`), six
disabled provider defaults, and zero running traders. The deployed source
archive still contains patch `0013`'s `addLiteLLMProviderAPIKey`: both chat paths
add the original provider credential as body `api_key`. LiteLLM's current
admission rejects caller-supplied provider credentials. Prepared patch `0020`
removes this forwarding and the old provider-key prerequisite in the shared
NOFX client; routed calls authenticate only with the dedicated mounted gateway
token. Synthetic tests cover both chat paths, absent provider credentials,
token rotation and concurrent calls. Publish/verify a new private
image through the declared build workflow before changing its deployment.
Do not weaken the gateway guard or start trading to test the repair.

Publication run [37568856616](https://github.com/Stuhlmuller/homelab/actions/runs/37568856616)
successfully built, published, signed and verified both private images from
`a4d5dc78247ddf3e5a6a540c38f7de019c8ed225`. The prepared deployment references
come directly from its digest artifact. Live rollout and native NOFX inference
acceptance remain pending; recheck stopped traders and simulations before merge.

PR [#1221](https://github.com/Stuhlmuller/homelab/pull/1221) merged as
`a6b2ee45deb04846dba4eeb66d896b5cbcf58427` on October 7 at 04:16 UTC.
All exact-head checks passed; the verified signed squash commit has the tested
tree. Immediately before merge, both required ExternalSecrets were Ready,
running traders and running/paused backtests each counted zero, and the lock
lookup succeeded with no results.

At 04:20 UTC, rollout was blocked by infrastructure: `zimaboard-2` reported
`Ready=Unknown` with `node.kubernetes.io/unreachable` taints. The unready
`argocd-application-controller-0` on that node was marked for eviction.
NOFX still reported the preceding revision `018218b0` and old image pair;
its Healthy status was not evidence of the new deployment. No manual restart,
force-sync, pod deletion or node mutation was performed. After node/controller
recovery, verify Argo observes the merged revision, both published digests run,
and traders remain stopped. Native NOFX inference and its Langfuse generation
also remain pending an authenticated NOFX browser session; do not bypass login
or activate trading for acceptance.

The subsequent October 7 UTC check found the node Ready and NOFX
Synced/Healthy at `2d8af0b36f04a032a27b98be106563c4d87701b6`, a descendant
of the rollout merge, with its Argo operation Succeeded. Both running containers
used the published backend `e42a347e...` and frontend `75e81702...` digests.
The served source includes patch `0020` and no longer contains
`addLiteLLMProviderAPIKey`. Fresh database checks again found zero running
traders and running/paused backtests; the lock lookup succeeded with no results.
This closes deployment verification, not inference acceptance. The browser
remained at Octelium login; an authenticated NOFX session is still needed for
the native nontrading AI test and matching Langfuse generation.

### Retirement gap: retained OpenClaw configuration

Live inspection still found an enabled `codex` plugin, the OpenAI provider
pointing at the ChatGPT Codex backend, subscription auth-profile references,
and `openai/gpt-5.5` / `openai/gpt-6-astra` model and allowlist entries.
The default uses LiteLLM, but full subscription retirement is not established.
`assistant/bootstrap.py` recursively merges providers/models and appends to
existing allowlists, so omitting old entries from the managed patch does not
remove them. The prepared migration replaces provider/model maps, restricts each
configured agent to the gateway model, disables OpenAI/Codex plugins, and removes
subscription auth-profile references. Original config and private credential
files are retained, not revoked or erased. Offline regression covers legacy
defaults, non-main overrides, unrelated settings and idempotence. Deployment is
pending the merge hold; inspect session overrides and actual-agent traces before
claiming every runtime uses LiteLLM.
The offline CLI displays 16 old Codex model/runtime associations among 37
stored sessions, but these are not proof of current routing overrides. Native
read-only store projection found no explicit model/provider/runtime overrides;
the running gateway resolved all 29 visible sessions (including two archived)
to `openrouter/free` and native `openclaw`, with none active or runtime-locked.
Do not rewrite historical usage to look migrated. Both focused OpenClaw checks
and the full static gate passed for the prepared config migration.

### Prepared tracing correction

The exporter now declares chat completions as `generation`, including streamed
responses, and sends `x-langfuse-ingestion-version=4`. The
[current OTEL contract](https://langfuse.com/integrations/native/opentelemetry)
documents that explicit observation types win and that omitting this header can
delay v4 visibility by up to ten minutes. These changes await deployment and a
new streamed agent trace; the earlier observations are not relabeled.

### Operational finding: Langfuse worker instability

The earlier read-only check found 67 worker restarts and a non-retryable
ClickHouse `system.query_log` read error (3400 bytes read, 3456 expected),
reported by `v4-legacy-api-usage-job`. Ingestion eventually completed, so this
does not establish the cause of its delay. Diagnose the worker termination and
ClickHouse part integrity before proposing repository-owned recovery; do not
delete data or restart workloads manually. No repair was performed. After the
October 10 Valkey recovery, the restarted worker is Ready but that legacy job
now reports `system.query_log` missing under the declared diagnostic quarantine.
Fresh generation ingestion succeeded, so this error does not block current
telemetry; the periodic job still needs a separate compatibility fix.
