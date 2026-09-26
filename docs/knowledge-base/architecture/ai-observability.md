# AI observability

Langfuse is the intended operator UI for prompts, outputs, errors and token
usage. The service and distinct app-key producers are staged first; current
OpenClaw/LiteLLM runtime configuration and the existing OpenClaw master-key
alias remain unchanged. Caller activation is a separate implementation PR;
this foundation contains no activation template or gateway hook. See the [gateway contract](../../../clusters/homelab/apps/litellm/README.md)
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

The caller inventory combines the September 20 runtime audit with a read-only
September 26 refresh (18:48-18:52 UTC) of AFFiNE, Multica, OctoBot and Cordium.
OpenClaw's desired state reflects the September 26 default-branch change; its
new free-model runtime and telemetry still need live acceptance.

| Caller | Observed configuration | Remaining acceptance |
| --- | --- | --- |
| OpenClaw | Desired `openrouter/free` for interactive turns, heartbeat and schedules; Astra OAuth retained for recovery | Verify real free-model turn content/usage through LiteLLM to Langfuse as the sole usage exporter. Preserve the selected model and recovery metadata. Direct Astra recovery is not covered by gateway-only telemetry. |
| NOFX | Provider/model credentials held in encrypted application state | Publish/test the maintained gateway-routing image, preserve provider/model and prove no provider-key leakage into telemetry. |
| n8n | Active workflow `s1JVSbnvnmHMCbty` uses AWS Bedrock Claude 3 Sonnet in `us-west-2` | Explicitly excluded by the operator on September 20. Leave its model, encrypted AWS credential and workflow unchanged; n8n is not covered by Langfuse in this rollout. |
| AFFiNE | App/PostgreSQL/Redis suspended at zero replicas; Copilot and BYOK disabled | No active AI workload; route through the gateway if enabled later. |
| Multica | Three Ready pods; server assist unconfigured; zero agent, runtime, daemon-connection and queued-task rows in read-only DB counts | No configured server inference or registered user runtime. Unregistered external agents remain outside this evidence. |
| OctoBot | Live `daily_trading` profile; all three AI evaluators and AIIndexTradingMode disabled | No configured active AI evaluator. Installed AI service/agent flags do not establish usage; credentials and actual traffic were not rechecked. |
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
`scripts/ci/langfuse-staging-check.py` proves existing caller credentials remain
unchanged and the incomplete activation hook/template is absent. A follow-up
must preserve current provider, model, image, bootstrap ordering and execution
budgets, including the September 26 `openrouter/free` defaults for interactive,
heartbeat and scheduled work. Astra's retained metadata is not the default.
Pinned OpenClaw 2026.9.2 and LiteLLM 1.80.8 source also establish a proposed
no-migration gateway path for the new free model: retain the PVC-backed
OpenRouter key in `Authorization`, send the separate mounted app key through
secret-backed `x-litellm-api-key`, and forward only the upstream bearer as
in-memory inference `api_key` through authenticated OpenClaw handling. A
September 26 offline proof exercised real FastAPI/SDK authentication, parsed-body
transfer and OpenRouter translation against a mock transport: provider bearer
and `openrouter/free` survived, gateway credentials stayed out of provider
requests/spans, and prompt/output plus 8/1 token counts were preserved. This is
not part of this foundation or live-verified. Preserve the free model and
redact success/error telemetry. Use gateway-only export for routed OpenClaw inference:
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
Ready token Secret and published image containing source patch `0013`, applied
after the owned-spot competition patch `0012`.
The September 26 main integration replayed all 13 patches against the pinned
source. Native Go historical gateway tests passed with `-race`, and focused
spot/ownership/lifecycle tests passed. Pinned Linux backend/frontend build
acceptance remains an exact-head CI gate; no local Docker binary was available.
The request-model review found that validating only the configured client model
missed `CallWithRequest` overrides. Gateway patch `0013` also validates the final
model after defaulting and before network/retries. Its regression requires zero
HTTP attempts for unsupported routed models and preserves direct overrides.

## Admission blocker and validation

The September 26 offline audit reproduced caller-selected Langfuse credentials
in LiteLLM 1.80.8: `function_setup` extracts dynamic callback fields before the
pre-call hook. The native authentication-failure path also calls it on the
original request body, including failures before custom authentication runs.
Clearing a later parsed-body copy or merely rejecting in custom authentication
does not close both paths. Source: `proxy/common_request_processing.py`,
`proxy/auth/auth_exception_handler.py` and `proxy/utils.py` in the pinned SDK.
No live exposure was established. The unsafe staged hook, ConfigMap, activation
patch and its incomplete SDK fixture were removed from this prerequisites PR;
isolated activation work must prove a complete pre-auth admission boundary
before publication/enablement. This foundation introduces no testing-only
dependency override or SDK monkeypatch.

The future SDK check must match the deployed Python 3.13 / LiteLLM 1.80.8 /
OpenAI 2.8.0 / HTTPX 0.28.1 / OpenTelemetry SDK 1.25.0 packages verified on
September 26. Exercise actual startup, accepted and rejected requests,
credential-marker redaction, streaming and exact provider usage. Native
failure spans can include provider-echoed credentials, so retain only safe
error type/status; exclude arbitrary provider bodies and tracebacks. Clean
both request snapshots and `metadata.headers`. Keep INFO logging, disable
raw-request logging and do not serialize full inference arguments. Captured
prompt/output content must remain behind Octelium and Istio access controls.

The protected full apply owns the S3 plan and apply because Application-only
filters omit that sibling unit; targeted `langfuse` apply is rejected.
Source and offline validation do not prove
that those resources exist. See [[gitops-flow]] and
[[../operations/validation-gates]].
