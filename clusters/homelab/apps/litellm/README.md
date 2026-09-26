# LiteLLM app attribution

LiteLLM currently retains its existing provider and master-key configuration.
The Langfuse callback and app authentication are staged in the
[pending activation patch](../../../../docs/examples/langfuse/activate-callers.patch),
outside the active Helm values. Apply only through a reviewed follow-up after
the [readiness gates](../langfuse/README.md#caller-activation) pass.

The pending configuration sends requests, outputs, usage and errors to the
homelab Langfuse project through a thin wrapper around LiteLLM's native
Langfuse OTLP exporter.
Langfuse owns the observability UI; LiteLLM does not need another database just
to label callers.

`app_identity.py` uses LiteLLM's custom-auth and pre-call callback interfaces.
Separate generated `/homelab/<app>/litellm-token` parameters identify NOFX
and Multica; OpenClaw uses `/homelab/openclaw/litellm-app-token`. Its existing
`litellm-token` remains the master-key alias until activation switches the
consumer. The `litellm-app-keys` ExternalSecret mounts those keys
for later file mounting. After activation, app keys permit model discovery and inference only; the master key
is reserved for the operator. Incoming identity labels are replaced with the
authenticated app name in Langfuse `userId`, trace name, metadata and `app:*`
tags. A caller's session ID is retained.

The `openrouter/free` alias preserves NOFX's current provider model. Its
maintained client can forward the original provider key separately from its
gateway bearer key. The pre-call hook removes credentials from LiteLLM's saved
request copy before telemetry; INFO logging and disabled raw-request capture
are required. The provider client still needs the original key in memory.
Failure spans retain error type/status only: provider error bodies and
tracebacks can echo credentials, so neither is exported. Successful request,
response and usage capture remains unchanged.
Verify new callbacks against the credential-marker regression before enabling
them; never serialize the full inference argument dictionary.

In Langfuse, filter by `app:nofx` (or another app), inspect traces for prompts,
responses and failures, and group token usage by user. Provider-reported token
counts and price availability determine token/cost completeness; subscription
OAuth traffic is not the same as billable OpenAI API traffic.

Keys reload on each request from the Secret volume. After rotating an SSM
value, update both consuming ExternalSecret revisions because they use
`OnChange`. Increment `app-identity-revision` in `values.yaml` when editing the
hook; the fixed ConfigMap name is shared with the Helm source.

## Validation and rollout

Run `scripts/ci/litellm-attribution-check.py` with `litellm[proxy]==1.80.8` and
`opentelemetry-api==1.45.0` installed. It tests real LiteLLM types, plugin
loading, denied keys/admin routes, rotation, metadata spoofing and Langfuse
attribute extraction. An
offline provider-error fixture checks credential exclusion from both SDK
failure spans and proxy-parent spans.
Render both the pinned Helm chart and Kustomize overlay, then evaluate them
with `conftest test --policy policy` (the namespace is `main`).

Before changing an app's provider endpoint, verify its original model and
credentials work through the gateway, then verify a correlated live trace has
nonzero token usage and input/output. Gateway health alone is insufficient.
Langfuse project initialization must finish before the first request; the
Application dependency orders registration, not readiness.

The September 20 live inspection found the existing `OPENAI_API_KEY` is still
the `REPLACE_ME` placeholder. Do not migrate working subscriptions or Bedrock
workflows to `openai-default`. Their provider/model and credential contracts
must be preserved and verified during their individual migrations.

The operator explicitly deferred n8n migration on September 20; its existing
Bedrock credential and workflow remain unchanged, outside this rollout's
Langfuse coverage.

Sources: [custom authentication](https://docs.litellm.ai/docs/proxy/custom_auth),
[Langfuse integration](https://langfuse.com/integrations/gateways/litellm).
