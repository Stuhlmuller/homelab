---
name: bootstrap-homelab
description: Use when the user wants to bootstrap or repair the Debian homelab nodes with Ansible, especially for rolling cluster updates, Tailscale recovery, or controlled host reconciliation.
---

# Bootstrap Homelab

Use the existing codified bootstrap flow instead of running one-off Ansible commands on individual hosts.

## Validate first

Run the checks in `.codex/skills/validate-homelab/SKILL.md` before changing live host state.

## Rolling bootstrap

```bash
./scripts/bootstrap-rolling.sh
```

The script already bootstraps in the safe order `zimaboard-1`, `zimaboard-2`, then `zimaboard-0`, and it revalidates the cluster after each host. Do not parallelize node changes.

## Tailscale reconciliation

For Tailscale-only repair, use the dedicated playbook instead of a full bootstrap:

```bash
make reconcile-tailscale
```

That expands to `ansible/playbooks/reconcile-tailscale.yml` with the production inventory.

## Degraded cluster mode

Only use degraded mode when quorum still exists and the user has accepted that risk:

```bash
SKIP_UNREACHABLE=1 ALLOW_DEGRADED_CLUSTER=1 ./scripts/bootstrap-rolling.sh
```
