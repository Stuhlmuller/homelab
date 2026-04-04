---
name: deploy-homelab
description: Use when the user wants the live homelab deployed end to end, including repository validation, AWS prerequisite checks, rolling bootstrap, OpenTofu and Terragrunt plan and apply, and post-deploy smoke tests.
---

# Deploy Homelab

Use the repo's deployment harness. It already sequences validation, bootstrap, OpenTofu, and workload checks.

## Primary command

```bash
./scripts/deploy-live.sh
```

## Common flags

- `--skip-bootstrap` when the Debian hosts are already provisioned and you only need the OpenTofu or Nomad rollout
- `--allow-degraded-cluster` only when the user approves a quorum-safe degraded rollout

## What this runs

- `make validate`
- `./scripts/validate-aws-ssm.sh`
- `./scripts/validate-aws-kms.sh`
- `./scripts/validate-live-cluster.sh`
- `./scripts/bootstrap-rolling.sh` unless bootstrap is skipped
- `terragrunt run --all --tf-path tofu plan --working-dir terraform/live/homelab`
- `terragrunt run --all --non-interactive --tf-path tofu apply --working-dir terraform/live/homelab`
- `./scripts/validate-live-workloads.sh`

## Guardrails

- Stop if the local repo validation fails.
- Stop if live preflight fails and the user has not explicitly approved degraded mode.
- Report absolute dates when summarizing live deployment status.
