# CI/CD

Tags: #runbooks #github-actions #ci-cd

Source: `docs/ci-cd.md`

## Pipeline Shape

- `Terragrunt Plan` runs on pull requests. It always runs static checks,
  Conftest, and Checkov. Trusted same-repo PRs can join the tailnet and run a
  live Terragrunt plan.
- `Terragrunt Apply` runs after merge to `main` and through
  `workflow_dispatch`. It repeats static checks, joins the tailnet, and applies
  the live Terragrunt phases in order: Argo CD bootstrap, SSM parameter
  declarations, Entra application registrations, Argo CD Application
  registrations, and Kubernetes secret materialization.
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
  Trusted same-repo PR plans render saved `plan.out` files with
  `terragrunt show -no-color plan.out` and replace the managed plan section in
  the PR description after each successful plan run.
- Automatic PR plans skip `IaC/live/aws-ssm-parameters` because it refreshes
  managed KMS, IAM, and SSM resources that require the protected apply role.
  They also skip `IaC/live/kubernetes-secrets`; protected apply runs those
  stacks after review.

## Environments

- `homelab-plan`: same-repository PR live plans.
- `homelab-production`: post-merge applies, reviewer-gated, branch-limited to
  `main`.

Both need `TS_AUTH_KEY` and `KUBE_CONFIG_B64`. AWS role values are documented in
the source runbook. `homelab-production` also needs
`AWS_TERRAGRUNT_APPLY_ROLE_ARN`, `AZUREAD_CLIENT_ID`, `AZUREAD_TENANT_ID`, and
`AZUREAD_CLIENT_SECRET`; the apply role must include OpenTofu state KMS access
to `alias/homelab-opentofu` in `us-east-1`.

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

Set `TERRAGRUNT_PLAN_MARKDOWN` locally to write the same rendered plan markdown
that the GitHub workflow places in the pull request body.
