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

The same read-only check found 67 worker restarts and a non-retryable
ClickHouse `system.query_log` read error (3400 bytes read, 3456 expected),
reported by `v4-legacy-api-usage-job`. Ingestion eventually completed, so this
does not establish the cause of its delay. Diagnose the worker termination and
ClickHouse part integrity before proposing repository-owned recovery; do not
delete data or restart workloads manually. No repair was performed.
