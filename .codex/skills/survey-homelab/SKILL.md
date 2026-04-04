---
name: survey-homelab
description: Use when the user wants a read-only survey of the homelab, asks which Zima boards are healthy, or wants a quick status snapshot before any changes are made.
---

# Survey Homelab

Run the repo's read-only survey entry point instead of rebuilding the checks by hand.

## Primary command

```bash
./scripts/survey-cluster.sh
```

## What to report

- Host reachability for `10.1.0.200`, `10.1.0.201`, and `10.1.0.202`
- Core service state for `nomad`, `consul`, `docker`, and `tailscaled`
- `nomad node status -self` output when the host is reachable
- `consul members` output when the host is reachable

## Guardrails

- Treat this workflow as read-only.
- If the user wants an authoritative deployment gate, follow with the checks in `.codex/skills/validate-homelab/SKILL.md`.
- If the survey shows a host is missing, say so with the concrete IP and do not infer that bootstrap or deployment is safe.
