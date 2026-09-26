# AI observability

Langfuse is the intended operator UI for prompts, outputs, errors and token
usage. The service and distinct app-key producers are staged first; current
OpenClaw/LiteLLM runtime configuration and the existing OpenClaw master-key
alias remain unchanged. The off-graph activation patch adds gateway app
authentication and direct OpenClaw OTLP only after prerequisite readiness. See the [gateway contract](../../../clusters/homelab/apps/litellm/README.md)
and [Langfuse deployment](../../../clusters/homelab/apps/langfuse/README.md).

## Rollout evidence

Read-only inspection on 2026-09-26 found no Langfuse namespace, Application,
PVCs or staged caller Secrets. Existing LiteLLM, OpenClaw and NOFX Applications
were Synced/Healthy. All four nodes were Ready without MemoryPressure. The
proposed 1,350m CPU / 2,816Mi memory requests fit on `acer` alone; actual node
memory use was 58%, 74%, 85% and 70% (`acer`, `zimaboard-0/1/2`). Scheduling
feasibility does not prove runtime stability: existing limits overcommit every
node. The healthy NFS provisioner and an existing QNAP mount reported about
904Gi free for the proposed 128Gi of claims. Recheck capacity before rollout.

The September 20 inspection found LiteLLM's OpenAI credential was `REPLACE_ME`;
provider usability has not been reverified. A Ready ExternalSecret alone does
not establish a usable provider.

The caller inventory below is the September 20 runtime audit, with OpenClaw's
desired state updated from the September 26 default-branch change. Its new
free-model runtime and telemetry still need live acceptance.

| Caller | Observed configuration | Remaining acceptance |
| --- | --- | --- |
| OpenClaw | Desired `openrouter/free` for interactive turns, heartbeat and schedules; Astra OAuth retained for recovery | Verify real free-model turn content/usage through LiteLLM to Langfuse as the sole usage exporter. Preserve the selected model and recovery metadata. Direct Astra recovery is not covered by gateway-only telemetry. |
| NOFX | Provider/model credentials held in encrypted application state | Publish/test the maintained gateway-routing image, preserve provider/model and prove no provider-key leakage into telemetry. |
| n8n | Active workflow `s1JVSbnvnmHMCbty` uses AWS Bedrock Claude 3 Sonnet in `us-west-2` | Explicitly excluded by the operator on September 20. Leave its model, encrypted AWS credential and workflow unchanged; n8n is not covered by Langfuse in this rollout. |
| AFFiNE | Copilot and BYOK explicitly disabled | No AI traffic to migrate; route through the gateway if enabled later. |
| Multica | Three Ready app pods; server assist has no provider/model credentials or model-client process | No configured server inference. User-owned agent runtimes require their own inventory before claiming coverage. |
| OctoBot | Live `daily_trading` profile; AI evaluators disabled and provider credentials absent | No active AI calls to migrate. Dormant `ai_trading`/`gpt_trading` profiles and installed AI tentacles do not establish usage. |
| Cordium | One Ready workspace, visible supervisor/Podman processes only; no model flags | Nested user workloads remain unverified: read-only `podman ps` fails on overlay-on-overlay storage. Do not change its storage driver merely to expand this audit. |

Except for the explicitly deferred n8n workflow, the migration is incomplete
until each active caller produces a correlated
Langfuse generation with expected app identity, model, input/output and token
usage. A healthy gateway, chart render or synthetic attribute test alone does
not satisfy that gate. Record any provider limitation explicitly.

## Staging boundary

[The activation runbook](../../../clusters/homelab/apps/langfuse/README.md#caller-activation)
requires SSM/S3 reconciliation, Ready Secrets and initialized Langfuse before
caller changes merge. Its UI gate also requires the separate authenticated
Octelium catalog apply and protected `octelium-public-tunnel.yml` DNS workflow;
Terragrunt alone does not publish the route. Use the same reviewed current-main
SHA and verify the authenticated route before activating callers.
`scripts/ci/langfuse-staging-check.py` proves existing
caller credentials remain unchanged and applies the pending patch in scratch
before exercising the OpenClaw fixtures. Overlapping OpenClaw changes must
refresh that artifact; it must preserve the current provider, model, image and
execution budgets. The activation fixture includes the existing batched CLI
ordering and failure checks, including telemetry-plugin enable/verification.
It preserves the September 26 `openrouter/free` selection for interactive,
heartbeat and scheduled work; Astra's retained metadata is not the active
default.
Pinned OpenClaw 2026.9.2 and LiteLLM 1.80.8 source also establish a proposed
no-migration gateway path for the new free model: retain the PVC-backed
OpenRouter key in `Authorization`, send the separate mounted app key through
secret-backed `x-litellm-api-key`, and forward only the upstream bearer as
in-memory inference `api_key` through authenticated OpenClaw handling. This is not
implemented or live-verified. Before activation, test both keys end to end,
preserve the free model and redact success/error telemetry. Replace the staged
native OTLP activation with gateway-only export for routed OpenClaw inference:
the pinned native plugin exports both
[per-call](https://github.com/openclaw/openclaw/blob/v2026.9.2/extensions/diagnostics-otel/src/service-recorders-model.ts)
and [run-total](https://github.com/openclaw/openclaw/blob/v2026.9.2/extensions/diagnostics-otel/src/service-recorders-usage.ts)
token usage, with no supported model-span filter. Sending those plus gateway
generations risks overcounting; disabling native metrics alone does not remove
span usage. Gateway-only omits native agent/tool lifecycle spans and direct
Astra recovery calls. Verify actual Langfuse totals against one request before
claiming accounting coverage. OpenRouter account
`/credits` and `/key` views would not work through the gateway. Do not copy the
OpenRouter-issued key into SSM; see the existing
[credential contract](../../../clusters/homelab/apps/openclaw/README.md) and
pinned [provider headers](https://github.com/openclaw/openclaw/blob/v2026.9.2/src/config/types.models.ts)
and [gateway authentication](https://github.com/BerriAI/litellm/blob/v1.80.8-stable/litellm/proxy/auth/user_api_key_auth.py).
The distinct future OpenClaw key is
`/homelab/openclaw/litellm-app-token`, leaving the live token alias untouched.
NOFX similarly stages its ServiceAccount, hashed routing ConfigMap and dedicated
token Secret without changing the active backend Pod spec. Its separate
`docs/examples/langfuse/activate-nofx.patch` requires an activated gateway,
Ready token Secret and published image containing source patch `0012`.

## Validation

The CI dependency check uses pinned Python 3.12 through `setup-python` because PyPI
native wheels require system libraries not provided by Nix's Python loader.

The pinned LiteLLM test exercises real auth types and exporter attribute
mapping, including caller spoofing, denied administration routes, key rotation,
token fields, and provider-credential redaction from stored request snapshots.
An offline September 26 failure-path test also found that the native exporter
copies provider-echoed credentials into exception events and `error.message`.
The staged exporter must retain only safe failure type/status, never arbitrary
provider error bodies or traceback text, while preserving successful
prompt/output/usage capture. Its regression covers SDK and proxy-parent spans.
Provider keys remain available to the in-process inference client; do not
enable DEBUG, raw request logging, or unreviewed callbacks that serialize the
whole request. App request/response bodies are intentionally captured by
Langfuse and access is restricted through Octelium and Istio.

The protected full apply owns the S3 plan and apply because Application-only
filters omit that sibling unit; targeted `langfuse` apply is rejected. Local state-backed AWS planning was blocked by
expired SSO during this inspection. Source and offline validation do not prove
that those resources exist. See [[gitops-flow]] and
[[../operations/validation-gates]].
