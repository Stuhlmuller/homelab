# LiteLLM app attribution

The gateway exposes `openrouter/free` to Multica using the dedicated
`/homelab/litellm/openrouter-api-key` SSM credential. It translates through
LiteLLM's OpenAI-compatible transport to OpenRouter `/api/v1`, preserving late
SSE usage chunks. `openai-default` remains unchanged. OpenClaw and NOFX are not
migrated by this change.

`gateway.py` starts the native single-worker proxy with a pure-ASGI admission
guard. Request-level callback/exporter overrides are rejected before native
authentication, including failure logging. `app_identity.py` authenticates
file-mounted app keys and emits Langfuse generations with trusted `app:multica`
attribution. Multica may discover models and call free-model chat completions;
it cannot administer the gateway or override provider credentials, URLs,
fallbacks or mock responses. Its provider key never reaches the runtime.

Langfuse receives prompts, outputs, provider usage and safe error type/status.
Authentication headers and provider credentials are removed from telemetry
snapshots; arbitrary provider errors/tracebacks are excluded. Raw request
logging is disabled. Langfuse project credentials are mounted from
`litellm-telemetry`; its OTLP endpoint is committed in `gateway.py`. No additional
LiteLLM database is required. The free router can select different underlying
models; its returned model and provider usage are the accounting evidence.

## Validation and activation

Run the full repository static gate and `scripts/ci/litellm-attribution-check.py`
with the pinned Python dependencies in `.github/workflows/validate.yml`. The
latter exercises native startup/authentication, rejected logging/routing
controls, Multica inference, credential redaction, streaming and exact usage
against an inert upstream transport. It does not prove live delivery.

**Do not merge/activate until prerequisites are ready:** complete the protected
[Langfuse workflow](../langfuse/README.md#validation), provision the dedicated
OpenRouter key with the declared `IaC/live/litellm-openrouter-key` unit, and
require initialized Langfuse plus Ready
`litellm-app-keys`, `litellm-telemetry` and `multica-litellm` ExternalSecrets.
The official OpenRouter provider `0.3.19` issues `homelab-litellm` and writes
its one-time plaintext result directly to the SSM SecureString
`/homelab/litellm/openrouter-api-key`. No placeholder or local random token is
used. The shared SSM unit grants reader access but does not own this parameter.

Bootstrap a management key once in the OpenRouter account and store it as the
`homelab-production` GitHub environment secret `OPENROUTER_MANAGEMENT_KEY`.
The protected full apply or `argocd_app=litellm` dispatch injects it only into
the provider, then plans, policy-checks and applies the saved key plan before
Application registration. Targeted LiteLLM apply assumes the prior Langfuse
prerequisite apply has reconciled shared SSM reader permissions. PR plans never
receive the management credential or this unit's sensitive state. Runtime Pods
never receive the management key. Ordinary inference keys cannot create keys.
See [OpenRouter management authentication](https://openrouter.ai/docs/guides/overview/auth/management-api-keys).

Retain encrypted OpenTofu state: OpenRouter returns plaintext only at creation;
importing a key hash cannot recover it. Both key and parameter prevent accidental
destruction; rollback retains them. If SSM publication fails after issuance,
retry using the retained state. Do not recreate keys outside this resource.
A new OnChange Secret revision is needed after a reviewed key rotation. Langfuse key rotation also requires a
Git-controlled gateway rollout because its exporter loads credentials at startup.
Application dependency ordering alone does not establish readiness.

Render pinned chart `0.1.832` and both Kustomize overlays; run Conftest policy
checks before rollout. After sync, require one real Multica OpenCode task,
one Langfuse generation with `app:multica`, prompt/output and nonzero usage,
and no credential values in exported data. Verify the authenticated Langfuse UI
through Octelium. Merely seeing a selectable model is not inference acceptance.

Rollback the Git change and remove the copied
`/home/multica/.config/opencode/opencode.json` through a reviewed runtime init
change if reverting the OpenCode integration; it resides on the retained PVC.
Restore agents that selected `litellm/openrouter/free` to their prior runtime
and model. Retain Multica and Langfuse PVCs and SSM credentials.

Read-only inspection on 2026-09-29 UTC found Multica Synced/Healthy, LiteLLM
OutOfSync/Degraded with one running gateway pod, no Langfuse Application, and
`litellm-app-keys` failing secret synchronization. Live activation is blocked;
no inference or telemetry delivery has been claimed.

The operator explicitly deferred n8n migration on September 20; its existing
Bedrock credential and workflow remain unchanged, outside this rollout's
Langfuse coverage.

Sources: [custom authentication](https://docs.litellm.ai/docs/proxy/custom_auth),
[Langfuse integration](https://langfuse.com/integrations/gateways/litellm).
