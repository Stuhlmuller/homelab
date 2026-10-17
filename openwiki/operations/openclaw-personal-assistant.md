---
type: operation
title: "OpenClaw personal assistant"
description: "OpenClaw GitHub installation-token exchange, model routing, managed assistant behavior, and remaining deployment acceptance."
tags: ["homelab", "navigation"]
sources:
  - id: openwiki-source-cce2f8f33e3b3639655d2b33
    resource: repo://clusters/homelab/apps/openclaw/assistant/bootstrap.py
  - id: openwiki-source-1a1a01e3db3c30a111cb3145
    resource: repo://clusters/homelab/apps/openclaw/assistant/config.json
  - id: openwiki-source-b26876230e53fd853d7bcbea
    resource: repo://clusters/homelab/apps/openclaw/values.yaml
generated: { by: "codex", at: "2026-10-10T23:00:00.726Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-10T23:10:58.872Z
---

# OpenClaw personal assistant

Source: `clusters/homelab/apps/openclaw/README.md` and `assistant/`.

September 29 UTC GitHub diagnosis: the running app's bare `gh api` exited 4
asking for login, while its mounted App key authenticated successfully and the
installation already granted repository write permissions. App credentials
were present; the missing installation-token exchange caused CLI access failure.
The managed `assistant/gh` wrapper now renews a homelab-only token per command,
using private temporary native CLI configuration. Git HTTPS routes through the
same wrapper. No new App grants, personal token, or persistent token cache.
Local regression checks cover authentication and cleanup. An in-memory live
probe of the repository helper returned the requested token grants, listed only
`Stuhlmuller/homelab`, and successfully supplied Git credentials without exposing
them. Deployment acceptance still requires the new pod's normal PATH and Git
helper to pass authenticated reads. See the app README.
Validation: the full static gate, pinned app-template 4.4.0 Helm rendering,
and Kustomize rendering passed locally, including the executable helper mount.
The existing installation has broader grants (including secrets write and all
repositories) than this helper requests. Narrowing the App registration is a
separate owner-reviewed GitHub IaC task; this change scopes issued tokens only.

Current model routing: interactive turns, heartbeat, and managed jobs use
`openrouter/free` through LiteLLM with no fallback. The managed provider targets
`http://litellm.ai.svc.cluster.local:4000/v1` and authenticates with the dedicated
file-backed caller key; LiteLLM owns upstream OpenRouter authentication.
Bootstrap replaces provider/model maps and disables OpenAI/Codex plugins and
their active auth references. Private historical credentials and backups remain
intact, but do not provide an active subscription recovery route. Bootstrap
installs the Discord plugin at the pinned gateway version; the toolbox no
longer installs a Codex CLI or code-mode host.

September 7 owner request expands Claw from homelab operations to a natural
Discord assistant, Google Calendar, and computer shopping on Facebook Marketplace.
Managed instructions define private task/deal tracking, Calendar readback and
conflict checks, bounded seller outreach once a search brief exists, and explicit
authorization for purchases, firm offers, and appointments. Homelab repairs retain
the existing PR/CI/GitOps path. No broad live-cluster access is introduced.

The pinned toolbox adds gogcli 0.11.0 and enables only its bundled skill;
existing identity, memory, credentials, and unrelated settings are preserved.
The existing morning briefing includes connected personal sources without adding
another recurring job. Private calendar details and shopping location stay out of git.

Read-only live evidence: OpenClaw 2/2 Ready with zero restarts, Discord enabled;
no gog/Chromium executable or configured browser profiles. Google was selected
by the owner. Account OAuth, persistent file-backed credential setup, private
browser deployment/login, and hardware/budget/pickup criteria remain blockers.
Instructions are not proof of integrations or successful actions. The README
records acceptance and rollback; complete those before claiming live capability.

See [Workload Inventory](../workloads/inventory.md) and [OpenClaw Runtime State](openclaw-runtime-state.md).

September 21 execution-timeout repair: read-only logs showed an interactive
Discord turn stopped exactly 600 seconds after startup with `codex app-server
execution budget timed out`; the live default was 600 seconds. The installed
2026.9.2 deadline handler counts elapsed time even while tools make progress.
The managed default is now 3600 seconds. Heartbeats remain at 600 seconds and
the three managed jobs retain 240/180/600 seconds. The upstream deadline code
with a fake clock reproduced the exact error for an 11-minute turn under the
old limit and allowed it under the new limit, while retaining the one-hour
cutoff. The assistant CI check covers installation and background overrides;
the full static gate and pinned Helm/Kustomize rendering passed locally.
Live rollout and owner-task completion remain acceptance gates; rollback uses
the previous default and bundle digest through GitOps.

Separate finding from the same read-only logs: memory indexing repeatedly
reports the configured OpenAI embedding provider unavailable and refuses an
FTS-only fallback to protect its existing vector index. This is not the Codex
execution-deadline error. Follow up by inspecting the file-backed embedding
credential/provider contract before changing indexing settings; preserve the
existing index. Source: OpenClaw app logs, September 20-21, 2026 UTC.

Validation: assistant installer/scheduler preservation and idempotence checks,
Kustomize rendering, and the full `nix develop --command bash scripts/ci/static-checks.sh`
gate passed locally. Live rollout and account acceptance remain pending.

September 11 integration retains the newer heartbeat rule: check each optional
status, task, and daily-note path before reading; preserve real read failures.
The rollout digest includes that rule and the current runtime-storage bundle.

September 12 UTC hardening acceptance: all init containers exited zero; the
Pod reached 2/2 Ready, proxy HTTP returned 200, and the Discord connection and
read-only credential probe passed. Gateway and proxy reported UID/GID 1000,
zero effective capabilities, `NoNewPrivs: 1`, and seccomp filtering.

The cold rollout took about 21 minutes: toolbox installation took 8m22s and
bootstrap 10m02s. Argo terminated the sync operation after 15 minutes, then
reported Synced/Healthy when startup completed. Retain both observations when
assessing rollout success. This extends the existing
[Measured startup cost](openclaw-bootstrap-batching.md#measured-startup-cost); profile or batch
configuration writes through reviewed code, preserve backup and runtime gates,
and evaluate declared rollout budgets against the measured startup bound.
