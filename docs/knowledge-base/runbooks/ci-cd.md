# CI/CD

Tags: #runbooks #github-actions #ci-cd

Source: `docs/ci-cd.md`

## Pipeline Shape

- `Lint` runs on pull requests with Super-Linter against changed files. It is an
  advisory shared lint signal; repository-specific blocking checks stay in
  `Terragrunt Plan` and `validate`.
- `Terragrunt Plan` runs on pull requests. It always runs static checks and
  Checkov first. Trusted same-repo PRs connect to Octelium, run a live
  Terragrunt plan, validate the rendered Terraform plan JSON with Conftest,
  and then run static Conftest checks. Forked PRs run static Conftest after the
  live plan skip notice.
- `Terragrunt Apply` runs after merge to `main` and through
  `workflow_dispatch`. It repeats static checks and Conftest, connects to
  Octelium, and applies the live Terragrunt phases in order: Argo CD bootstrap,
  SSM parameter declarations, Entra application registrations, Argo CD
  Application registrations, and Kubernetes secret materialization.
- Forked PRs never receive AWS, Octelium, or Kubernetes secrets.

## Security Model

- Workflows use `pull_request` and `push`, not `pull_request_target`.
- The lint workflow is a lightweight changed-file gate that preserves the
  required `Lint` status context without replacing the stricter static and
  Terragrunt gates. It checks diff whitespace, parses changed YAML, runs
  `bash -n` on changed shell scripts, and uses workflow concurrency to cancel
  stale lint runs for the same pull request.
- Policy Bot reads this repository's `.policy.yml` and requires every PR commit
  to have a GitHub-verified signature before normal review approval can satisfy
  the `policy-bot: main` branch protection check. The explicit comment path
  accepts only a `👍` comment from `rstuhlmuller`, including PRs opened by
  `rodman` and PRs where `rstuhlmuller` authored or committed changes; it does
  not read PR body text or other users' comments. The organization-member rule
  also opts into author and contributor approvals so matching Stuhlmuller
  approvals are not ignored as disqualified.
- External actions are pinned to full commit SHAs and checked by Conftest.
- Terragrunt plan and apply jobs restore and save a GitHub Actions cache for the
  Nix store after installing Nix. The cache key is derived from the runner OS,
  `flake.nix`, and `flake.lock`, with an OS-scoped fallback for nearby dev shell
  closures.
- GitHub token permissions default to none.
- AWS access uses GitHub OIDC and short-lived role sessions.
- Octelium uses a workload credential for User `homelab-ci`. The workflow
  publishes only Service `kubernetes-api.homelab` to
  `https://127.0.0.1:16443` with the gVisor implementation and no Octelium DNS.
  The policy-bound credential is the enforcement boundary; do not add
  auth-token `--scope` flags to this v0.35 connect path because scoped sessions
  are denied before the loopback listener is published.
- Kubeconfig is injected only from GitHub environment secrets and written
  locally with mode `0600`; CI rewrites the current cluster server to the
  loopback listener and sets the Kubernetes TLS server name to `10.1.0.199`.
  The unauthenticated curl readiness check only proves the TLS endpoint is
  reachable and may receive `401`; authenticated `kubectl version` is the real
  Kubernetes API validation.
- Plans are not uploaded as artifacts because they may include sensitive state.
  Trusted same-repo PR plans render saved `plan.out` files with
  `terragrunt show -no-color plan.out` and replace the managed plan section in
  the PR description after each successful plan run. The same job also renders
  local `plan.json` files from those saved plans and runs Terraform-plan
  Conftest policies before the PR description update.
- Automatic PR plans skip `IaC/live/aws-ssm-parameters` because it refreshes
  managed KMS, IAM, and SSM resources that require the protected apply role.
  They also skip `IaC/live/kubernetes-secrets`; protected apply runs those
  stacks after review.
- Validation and deployment workflows use Terragrunt commands as their repo
  entrypoints. Terragrunt logs may still show `tofu:` prefixes or
  `Failed to execute "tofu ..."` because Terragrunt shells out to OpenTofu
  internally; rerun or recover through the Terragrunt workflow/script instead
  of copying cache-directory OpenTofu commands.
- Terragrunt plan and apply phases use `--filter-affected` so run queues are
  limited to units changed between `main` and `HEAD`. In CI, the helper script
  prepares `main` to mean the PR base branch for plans or the previous push SHA
  for post-merge applies. Manual apply dispatches compare against `HEAD^`.
- Deleted Terragrunt units are a special case because current-tree
  `--filter-affected` runs cannot enter a directory that no longer exists.
  `scripts/ci/terragrunt-plan.sh` and `scripts/ci/terragrunt-apply.sh` detect
  deleted `IaC/**/terragrunt.hcl` files, create temporary empty Terragrunt
  units at those deleted paths, and rely on `IaC/root.hcl` so the fake units
  point at the same remote-state keys as the removed units. PR plans list the
  state resources and save destroy plans without rendering potentially
  sensitive values; production apply lists those state resources and applies
  the saved destroy plans before applying the current checkout.
- Stack-wide apply phases use Terragrunt's explicit
  `run --all --filter-affected --non-interactive -- apply ...` form so the run
  queue is accepted in Actions and OpenTofu flags such as `-auto-approve` are
  forwarded to OpenTofu instead of being parsed as Terragrunt CLI flags.

## Monitoring

Grafana's `GitHub PR Status` dashboard uses the provisioned GitHub Infinity
datasource to read public GitHub REST API endpoints for open pull requests,
pull requests with failing or pending status checks, and recent failed workflow
runs. Grafana-managed GitHub Actions alert rules are not provisioned while the
datasource is unauthenticated, because shared public API rate limits can turn
alert evaluations into noisy datasource-error pages. Re-enable them only after
adding a reviewed token-backed secret contract for Grafana.

## Environments

- `homelab-plan`: same-repository PR live plans.
- `homelab-production`: post-merge applies, reviewer-gated, branch-limited to
  `main`.

Both need `OCTELIUM_CI_AUTH_TOKEN` and `KUBE_CONFIG_B64`.
`AWS_ROLE_TO_ASSUME_HOMELAB` is used by both trusted PR plans and protected
post-merge applies, so it must trust the `homelab-plan` and
`homelab-production` GitHub OIDC subjects and include apply-level OpenTofu
state KMS access to `alias/homelab-opentofu` in `us-east-1`. The same role also
needs identity-based KMS access on the resolved `us-west-2` SSM SecureString
key ARN managed by `IaC/live/aws-ssm-parameters`; state-key-only access fails
during SSM provider refresh with `AccessDeniedException` for `kms:DescribeKey`.
The workflows resolve non-sensitive role/client/tenant values from GitHub
variables first and same-named secrets as a fallback, while
`AZUREAD_CLIENT_SECRET`, `OCTELIUM_CI_AUTH_TOKEN`, and `KUBE_CONFIG_B64` remain
secret-only inputs.

`IaC/live/azuread-applications` is planned and applied only when Entra
credentials are configured. Same-repository PR plans render AzureAD plans when
those values are present in `homelab-plan`; otherwise that PR plan phase is
skipped with a warning. Protected push applies need the values in
`homelab-production`. Without those credentials, push applies skip that phase
when the AzureAD stack did not change; AzureAD stack changes and manual
dispatches still fail fast so identity drift is not hidden.

## Octelium CI Route

The Octelium catalog in `docs/examples/octelium/homelab-services.yaml` owns
the CI transport contract:

- workload User `homelab-ci`;
- Policy `homelab-ci-kubernetes-api-access`;
- TCP Service `kubernetes-api.homelab -> tcp://10.1.0.199:6443`.

Apply the catalog with `octeliumctl apply --domain stinkyboi.com
docs/examples/octelium/homelab-services.yaml`, then create the credential with
`octeliumctl create cred --domain stinkyboi.com --user homelab-ci
--policy homelab-ci-kubernetes-api-access homelab-ci`. Store only the printed
credential token in GitHub environments as `OCTELIUM_CI_AUTH_TOKEN`.

The CI connector intentionally does not pass Octelium `--scope` flags. The
`homelab-ci-kubernetes-api-access` policy is attached to the workload
credential and limits access to the Kubernetes API Service; scoped auth-token
sessions on Octelium v0.35 are denied during session creation.

GitHub-hosted runners must reach `octelium-api.stinkyboi.com` from the
public Internet. Keep the Octelium cluster domain as `stinkyboi.com`; using
`octelium.stinkyboi.com` as the domain makes the client call
`octelium-api.octelium.stinkyboi.com`, which Cloudflare Universal SSL does not
cover without a paid nested wildcard certificate.

## Local Equivalents

```sh
nix develop --command pre-commit run --all-files
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/terragrunt-plan.sh
nix develop --command bash scripts/ci/conftest-policies.sh
nix develop --command bash scripts/ci/terragrunt-apply.sh
```

The pre-commit run is the closest local equivalent to the Super-Linter PR
check. GitHub Actions remains the source for the exact lint status contexts.

Local runs use the current `main` ref for Terragrunt's affected-unit
comparison. Refresh `main` before reproducing a GitHub plan or apply diff.

Manual apply dispatches compare against `HEAD^`; use the normal post-merge push
path when the affected range needs to span multiple commits.

Run apply only after the same checks have passed and the change has been
reviewed.

Set `TERRAGRUNT_PLAN_MARKDOWN` locally to write the same rendered plan markdown
that the GitHub workflow places in the pull request body.
