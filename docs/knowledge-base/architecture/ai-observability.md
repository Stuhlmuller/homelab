# AI observability

Langfuse is the operator UI for prompts, outputs, errors and token usage.
LiteLLM is the sole in-cluster inference gateway: it accepts only
`openrouter/free`, authenticates named callers with dedicated keys and emits
trusted application attribution to Langfuse. The provider credential is mounted
only by LiteLLM from `/homelab/litellm/openai-api-key`; it is an OpenRouter
credential despite the legacy SSM parameter name.

The gateway rejects request-supplied callback, tracing and credential overrides
before LiteLLM parses them. Langfuse credentials are file-mounted, never passed
by callers. See the [gateway contract](../../../clusters/homelab/apps/litellm/README.md).

## Caller inventory

| Caller | Gateway identity | State |
| --- | --- | --- |
| OpenClaw | `/homelab/openclaw/litellm-app-token` | Routed to `openrouter/free`; Codex subscription runtime removed. |
| Multica | `/homelab/multica/litellm-token` | OpenCode uses the internal gateway; Codex runtime removed. |
| NOFX | `/homelab/nofx/litellm-token` | Backend uses the internal gateway through a file-backed route and dedicated read-only token mount; its pinned image includes patch `0013`. |
| n8n | `/homelab/n8n/litellm-token` | Secret-backed OpenAI credential override targets LiteLLM. The idempotent CLI migration imports its managed credential as n8n's required one-element array, replaces Bedrock in `s1JVSbnvnmHMCbty` with `openrouter/free`, and exports its bootstrap key only for an empty config PVC. The gateway key never enters workflow JSON. |

AFFiNE has no active AI workload. OctoBot's AI evaluators are disabled. Cordium
may host user workloads and remains outside this cluster-owned routing contract.

## Current rollout dependency

An earlier ClickHouse logging change exposed a sync-wave dependency: its
generated ConfigMap followed the Deployment, so Argo waited for a Pod that
could not mount its configuration. [PR #1167](https://github.com/Stuhlmuller/homelab/pull/1167)
fixed the ordering. That logging override has since been removed; keep future
generated configuration ahead of its consumers. An existing sync can hold an
older revision until the declared 900-second controller timeout releases it.
See [[gitops-flow]] and Argo CD's
[timeout handling](https://github.com/argoproj/argo-cd/blob/v3.4.2/controller/appcontroller.go#L1454-L1465).

## Acceptance

Configuration is not acceptance. For each active caller, verify a real request
creates one Langfuse generation with its gateway app identity, `openrouter/free`,
input/output and provider token usage. Verify error traces do not expose bearer
credentials. A healthy Deployment, Argo sync or synthetic gateway test is not
enough.

The current live check on 2026-10-03 found Langfuse and the existing caller
Deployments healthy. It did not establish a post-change inference trace, because
the GitOps revision is not yet applied.
