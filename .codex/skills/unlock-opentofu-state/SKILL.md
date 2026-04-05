---
name: unlock-opentofu-state
description: Use when a Terragrunt or OpenTofu unit is stuck behind a stale state lock and the user wants to clear that specific lock without changing the infrastructure configuration.
---

# Unlock OpenTofu State

Use the repo helper so the unit path and lock ID stay explicit.

## Primary command

```bash
./scripts/unlock-terragrunt-unit.sh <terragrunt-unit-path> <lock-id>
```

Or through `make`:

```bash
make unlock-state UNIT=terraform/live/homelab/jobs/dokploy LOCK_ID=<lock-id>
```

## Guardrails

- Do not unlock state speculatively. The user should provide the exact unit path and lock ID.
- Keep `TG_TF_PATH=tofu` unless there is a deliberate reason to override it.
- After unlocking, rerun a focused `terragrunt plan` for that unit or rerun the deployment flow in `.codex/skills/deploy-homelab/SKILL.md`.
