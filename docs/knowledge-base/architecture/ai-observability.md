# AI observability

Langfuse is the intended operator UI for prompts, outputs, errors and token
usage. LiteLLM supplies the shared inference endpoint and authenticates callers
with distinct app keys. See the [gateway contract](../../../clusters/homelab/apps/litellm/README.md)
and [Langfuse deployment](../../../clusters/homelab/apps/langfuse/README.md).

## Rollout evidence

Read-only inspection on 2026-09-20 found no Langfuse Argo CD Application.
LiteLLM was healthy, but its OpenAI credential was `REPLACE_ME`. A Ready
ExternalSecret therefore did not establish a usable provider. Node memory use
was approximately 58%, 80%, 81% and 74%; validate scheduling and actual
datastore/web/worker memory before expanding this deployment.

| Caller   | Observed configuration                                                                        | Remaining acceptance                                                                                                                                                   |
| -------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OpenClaw | ChatGPT Codex OAuth subscription; direct Langfuse OTLP proposed                               | Verify real turn content/usage. Keep subscription until the user chooses API billing; opaque Codex turns may omit token counts.                                        |
| NOFX     | Provider/model credentials held in encrypted application state                                | Publish/test the maintained gateway-routing image, preserve provider/model and prove no provider-key leakage into telemetry.                                           |
| n8n      | Active workflow `s1JVSbnvnmHMCbty` uses AWS Bedrock Claude 3 Sonnet in `us-west-2`            | Explicitly excluded by the operator on September 20. Leave its model, encrypted AWS credential and workflow unchanged; n8n is not covered by Langfuse in this rollout. |
| AFFiNE   | Copilot and BYOK explicitly disabled                                                          | No AI traffic to migrate; route through the gateway if enabled later.                                                                                                  |
| Multica  | Three Ready app pods; server assist has no provider/model credentials or model-client process | No configured server inference. User-owned agent runtimes require their own inventory before claiming coverage.                                                        |
| OctoBot  | Live `daily_trading` profile; AI evaluators disabled and provider credentials absent          | No active AI calls to migrate. Dormant `ai_trading`/`gpt_trading` profiles and installed AI tentacles do not establish usage.                                          |
| Cordium  | One Ready workspace, visible supervisor/Podman processes only; no model flags                 | Nested user workloads remain unverified: read-only `podman ps` fails on overlay-on-overlay storage. Do not change its storage driver merely to expand this audit.      |

Except for the explicitly deferred n8n workflow, the migration is incomplete
until each active caller produces a correlated
Langfuse generation with expected app identity, model, input/output and token
usage. A healthy gateway, chart render or synthetic attribute test alone does
not satisfy that gate. Record any provider limitation explicitly.

## Validation

The pinned LiteLLM test exercises real auth types and exporter attribute
mapping, including caller spoofing, denied administration routes, key rotation,
token fields, and provider-credential redaction from stored request snapshots.
Provider keys remain available to the in-process inference client; do not
enable DEBUG, raw request logging, or unreviewed callbacks that serialize the
whole request. App request/response bodies are intentionally captured by
Langfuse and access is restricted through Octelium and Istio.

The protected full apply owns the S3 plan and apply because Application-only
filters omit that sibling unit; targeted `langfuse` apply is rejected. Local state-backed AWS planning was blocked by
expired SSO during this inspection. Source and offline validation do not prove
that those resources exist. See [[gitops-flow]] and
[[../operations/validation-gates]].
