# CI/CD

Tags: #runbooks #github-actions #ci-cd

Source: `docs/ci-cd.md`

## Pipeline Shape

- `Terragrunt Plan` runs on pull requests. It always runs static checks,
  Conftest, and Checkov. Trusted same-repo PRs can join the tailnet and run a
  live Terragrunt plan.
- `Terragrunt Apply` runs after merge to `main` and through
  `workflow_dispatch`. It repeats static checks, joins the tailnet, and applies
  the live Terragrunt stack.
- Forked PRs never receive AWS, Tailscale, or Kubernetes secrets.

## Security Model

- Workflows use `pull_request` and `push`, not `pull_request_target`.
- External actions are pinned to full commit SHAs and checked by Conftest.
- GitHub token permissions default to none.
- AWS access uses GitHub OIDC and short-lived role sessions.
- Tailscale uses an auth key because tailnet lock blocks the federated path for
  these runners.
- Kubeconfig is injected only from GitHub environment secrets and written
  locally with mode `0600`.
- Plans are not uploaded as artifacts because they may include sensitive state.
- Automatic PR plans skip `IaC/live/kubernetes-secrets`; protected apply runs
  the full `IaC/live` stack.

## Environments

- `homelab-plan`: same-repository PR live plans.
- `homelab-production`: post-merge applies, reviewer-gated, branch-limited to
  `main`.

Both need `TS_AUTH_KEY` and `KUBE_CONFIG_B64`. AWS role values are documented in
the source runbook.

## Tailscale CI Route

CI uses tags:

- `tag:github-actions-terragrunt-plan`
- `tag:github-actions-terragrunt-apply`

Prefer the repo-owned `homelab-exit-node` connector and its `10.1.0.199/32`
route to reach the Kubernetes API. Keep grants limited to TCP `6443`.

## Local Equivalents

```sh
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/terragrunt-plan.sh
nix develop --command bash scripts/ci/terragrunt-apply.sh
```

Run apply only after the same checks have passed and the change has been
reviewed.
