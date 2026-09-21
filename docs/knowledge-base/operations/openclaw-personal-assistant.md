# OpenClaw personal assistant

Source: `clusters/homelab/apps/openclaw/README.md` and `assistant/`.

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

See [[workloads/inventory]] and [[operations/openclaw-assistant-2026-09-05]].

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
[[openclaw-assistant-2026-09-05#Startup performance finding]]; profile or batch
configuration writes through reviewed code, preserve migration/backup gates,
and evaluate declared rollout budgets against the measured startup bound.
