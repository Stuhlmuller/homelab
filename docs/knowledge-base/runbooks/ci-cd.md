# CI/CD

Tags: #runbooks #github-actions #ci-cd

Source: `docs/ci-cd.md`

## Pipeline Shape

- `Terragrunt Plan` runs on pull requests. It always runs static checks and
  Checkov first. Trusted same-repo PRs can join the tailnet, run a live
  Terragrunt plan, validate the rendered Terraform plan JSON with Conftest,
  and then run static Conftest checks. Forked PRs run static Conftest after the
  live plan skip notice.
- `Terragrunt Apply` runs after merge to `main` and through
  `workflow_dispatch`. It repeats static checks and Conftest, joins the
  tailnet, and applies the live Terragrunt phases in order: Argo CD bootstrap,
  SSM parameter declarations, Entra application registrations, Argo CD
  Application registrations. The External Secrets AWS auth Secret is installed
  by a protected CI script before Argo CD app registration so decrypted runtime
  credentials do not enter OpenTofu state.
- Forked PRs never receive AWS, Tailscale, or Kubernetes secrets.

## Security Model

- Workflows use `pull_request` and `push`, not `pull_request_target`.
- Pull request commits must be SSH-signed by the repo-pinned `claw` signing
  key in `.github/allowed_signers`, with fingerprint
  `SHA256:aEGjgIntjDt20o2jFQdaHHEzDEYq5Vcm3oJ5qOFhFpA`.
- External actions are pinned to full commit SHAs and checked by Conftest.
- Terragrunt plan and apply jobs restore and save a GitHub Actions cache for the
  Nix store after installing Nix. The cache key is derived from the runner OS,
  `flake.nix`, and `flake.lock`, with an OS-scoped fallback for nearby dev shell
  closures.
- GitHub token permissions default to none.
- AWS access uses GitHub OIDC and short-lived role sessions.
- Tailscale uses an auth key because tailnet lock blocks the federated path for
  these runners.
- Kubeconfig is injected only from GitHub environment secrets and written
  locally with mode `0600`.
- Plans are not uploaded as artifacts because they may include sensitive state.
  Trusted same-repo PR plans render saved `plan.out` files with
  `terragrunt show -no-color plan.out` and replace the managed plan section in
  the PR description after each successful plan run. The same job also renders
  local `plan.json` files from those saved plans and runs Terraform-plan
  Conftest policies before the PR description update.
- Automatic PR plans skip `IaC/live/aws-ssm-parameters` because it refreshes
  managed KMS, IAM, and SSM resources that require the protected apply role.
  Protected apply creates a saved SSM plan, runs Terraform plan policy, and
  applies that saved plan. Runtime Kubernetes Secrets are installed by protected
  CI scripts rather than OpenTofu state.
- Validation and deployment workflows use Terragrunt commands as their repo
  entrypoints. Terragrunt logs may still show `tofu:` prefixes or
  `Failed to execute "tofu ..."` because Terragrunt shells out to OpenTofu
  internally; rerun or recover through the Terragrunt workflow/script instead
  of copying cache-directory OpenTofu commands.
- Terragrunt plan and apply phases use `--filter-affected` so run queues are
  limited to units changed between `main` and `HEAD`. In CI, the helper script
  prepares `main` to mean the PR base branch for plans or the previous push SHA
  for post-merge applies. Manual apply dispatches compare against `HEAD^`.
- Stack-wide apply phases use Terragrunt's explicit
  `run --all --filter-affected --non-interactive -- apply ...` form so the run
  queue is accepted in Actions and OpenTofu flags such as `-auto-approve` are
  forwarded to OpenTofu instead of being parsed as Terragrunt CLI flags.

## Monitoring

Grafana's `GitHub PR Status` dashboard uses the provisioned GitHub Infinity
datasource to read public GitHub REST API endpoints for open pull requests,
pull requests with failing or pending status checks, and recent failed workflow
runs. Grafana-managed alerts poll GitHub Actions every ten minutes and notify
through the normal homelab route when workflow runs enter `failure` or
`timed_out` during the two-hour alert window. Keep these queries
unauthenticated and conservatively scheduled unless a reviewed token-backed
secret contract is added.

## Environments

- `homelab-plan`: same-repository PR live plans.
- `homelab-production`: post-merge applies, reviewer-gated, branch-limited to
  `main`.

Both need `TS_AUTH_KEY` and `KUBE_CONFIG_B64`. `AWS_ROLE_TO_ASSUME_HOMELAB` is
used by both trusted PR plans and protected post-merge applies, so it must trust
the `homelab-plan` and `homelab-production` GitHub OIDC subjects and include
apply-level OpenTofu state KMS access to `alias/homelab-opentofu` in
`us-east-1`. The same role also needs identity-based KMS access on the resolved
`us-west-2` SSM SecureString key ARN managed by `IaC/live/aws-ssm-parameters`;
state-key-only access fails during SSM provider refresh with
`AccessDeniedException` for `kms:DescribeKey`. The workflows resolve
non-sensitive role/client/tenant values from GitHub variables first and
same-named secrets as a fallback, while `AZUREAD_CLIENT_SECRET`, `TS_AUTH_KEY`,
and `KUBE_CONFIG_B64` remain secret-only inputs.

`IaC/live/azuread-applications` is applied only when Entra credentials are
configured. Without those credentials, push applies skip that phase when the
AzureAD stack did not change; AzureAD stack changes and manual dispatches still
fail fast so identity drift is not hidden.

## Tailscale CI Route

CI uses tags:

- `tag:github-actions-terragrunt-plan`
- `tag:github-actions-terragrunt-apply`

Use the repo-owned `homelab-exit-node` connector's advertised `10.1.0.0/24`
route to reach the Kubernetes API at `10.1.0.199:6443`. Do not select it as a
full exit node in CI: Terragrunt still needs public AWS STS/KMS access, and
routing that traffic through the tailnet path has caused runner DNS timeouts
against `127.0.0.53`. Keep CI grants limited to TCP `6443` on the API host.

## Local Equivalents

```sh
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/terragrunt-plan.sh
nix develop --command bash scripts/ci/conftest-policies.sh
nix develop --command bash scripts/ci/terragrunt-apply.sh
```

Local runs use the current `main` ref for Terragrunt's affected-unit
comparison. Refresh `main` before reproducing a GitHub plan or apply diff.

Manual apply dispatches compare against `HEAD^`; use the normal post-merge push
path when the affected range needs to span multiple commits.

Run apply only after the same checks have passed and the change has been
reviewed.

Set `TERRAGRUNT_PLAN_MARKDOWN` locally to write the same rendered plan markdown
that the GitHub workflow places in the pull request body.
