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

NOFX remains staged until an image containing
`builds/nofx/patches/0013-litellm-runtime-routing.patch` is published and
pinned. Do not mount its route/token into the currently deployed image.

Sources: [LiteLLM custom authentication](https://docs.litellm.ai/docs/proxy/custom_auth),
[Langfuse LiteLLM integration](https://langfuse.com/integrations/gateways/litellm).
