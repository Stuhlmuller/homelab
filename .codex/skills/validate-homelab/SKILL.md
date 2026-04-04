---
name: validate-homelab
description: Use when the user asks to validate repository changes, confirm AWS SSM or KMS prerequisites, check Nomad and Consul quorum, or verify live homelab workloads before or after deployment.
---

# Validate Homelab

Use the repo's validation entry points in order. Do not replace them with one-off ad hoc checks unless you are fixing the validator itself.

## Repository-first validation

```bash
make validate
```

Stop here if local validation fails.

## Live preflight

Run these from the repo root when the user wants live validation:

```bash
./scripts/validate-aws-ssm.sh
./scripts/validate-aws-kms.sh
./scripts/validate-live-cluster.sh
```

Use `ALLOW_DEGRADED_CLUSTER=1` only when the user explicitly accepts a quorum-safe degraded rollout.

## Post-deploy smoke checks

```bash
./scripts/validate-live-workloads.sh
```

This validates Nomad jobs, required Nomad variables, Tailscale backend state, Traefik's ping endpoint, and the Dokploy HTTPS health endpoint.
