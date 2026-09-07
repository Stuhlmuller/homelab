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
