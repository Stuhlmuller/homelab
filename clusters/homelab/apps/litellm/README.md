# LiteLLM app attribution

LiteLLM currently retains its existing provider and master-key configuration.
Langfuse integration and app authentication are deferred to a separate
implementation PR. Activate only through a reviewed follow-up after
the [readiness gates](../langfuse/README.md#caller-activation) pass.

The intended integration sends requests, outputs, usage and safe errors to
the homelab Langfuse project. Langfuse owns the observability UI; LiteLLM does
not need another database just to label callers.

Separate generated `/homelab/<app>/litellm-token` parameters identify NOFX
and Multica; OpenClaw's future key uses `/homelab/openclaw/litellm-app-token`. Its existing
`litellm-token` remains the master-key alias until activation switches the
consumer. The `litellm-app-keys` ExternalSecret produces those keys for later
file mounting; no current gateway container consumes them. The activation
contract requires inference-only app keys, operator-only administration,
trusted app attribution and preservation of caller session IDs.

The pinned LiteLLM 1.80.8 SDK extracts request-level callbacks and dynamic
exporter credentials before pre-call hooks. Authentication failures can also
reprocess the original body before custom authentication runs. An offline
regression reproduced caller-selected Langfuse credentials on both paths.
The incomplete hook and activation template were removed from this foundation
change; they are not a safe activation recipe. The follow-up must enforce
admission before these paths and prove rejected requests cannot initialize
callbacks or redirect telemetry.

Preserve each app's original provider/model and credentials. Strip credentials
from request snapshots and headers before export, retain safe error type/status
only, and preserve successful prompt/output/usage capture. INFO logging and
disabled raw-request logging are required. Never serialize the full inference
argument dictionary or arbitrary provider error bodies/tracebacks.

After activation, Langfuse must support filtering and grouping by authenticated
app identity. Provider-reported usage and price availability determine token
and cost completeness; subscription OAuth traffic is not billable OpenAI API
traffic. Key rotation must account for the `OnChange` ExternalSecrets.

## Validation and rollout

Run `nix develop --command python3 scripts/ci/langfuse-staging-check.py` to
verify this foundation leaves callers unchanged and contains no activation
hook/template. The activation PR must supply production-matched offline
checks covering native startup, authentication failures, callback admission,
credential redaction, streaming and exact provider usage.
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
