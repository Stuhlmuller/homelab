# Agent Harness

This repository is structured so automated contributors can work safely:

- `ansible/` owns host bootstrap and base operating system configuration.
- `terraform/live/homelab/` owns declarative deployment into Nomad through
  Terragrunt/OpenTofu.
- `nomad/jobs/` owns the source jobspecs.
- `.codex/skills/` owns project-local Codex skills that wrap the validated
  operator workflows.
- `scripts/validate.sh` is the default pre-deployment gate.
- `scripts/survey-cluster.sh` is the default read-only cluster inspection tool.

## Safety rules

- Treat `10.1.0.201` as degraded until a fresh survey proves otherwise.
- Do not change live host state without running `make validate` first.
- Prefer read-only SSH inspection before changing bootstrap assumptions.
- Keep Traefik as the only public entry point for HTTP services.
- Store certificates on shared storage so a Traefik reschedule does not lose
  ACME state.
- Keep OpenTofu state and plan encryption enabled for every in-repo module.
- Keep secret values in AWS SSM Parameter Store; only commit SSM parameter names
  and non-secret defaults to git.
- Prefer file-backed runtime secrets such as `_FILE` paths over direct task
  environment injection.

## Default workflow

1. Run `./scripts/survey-cluster.sh`.
2. Run `make validate`.
3. Update Ansible or Nomad source files.
4. Re-run `make validate`.
5. Run `make validate-ssm` and `make validate-live-cluster` before touching the cluster.
6. Use `./scripts/deploy-live.sh` for full live rollout orchestration.

## Project-local skills

- `survey-homelab` maps to `./scripts/survey-cluster.sh`.
- `validate-homelab` maps to `make validate` and the live validation scripts.
- `bootstrap-homelab` maps to `./scripts/bootstrap-rolling.sh` and `make reconcile-tailscale`.
- `deploy-homelab` maps to `./scripts/deploy-live.sh`.
- `unlock-opentofu-state` maps to `./scripts/unlock-terragrunt-unit.sh`.
