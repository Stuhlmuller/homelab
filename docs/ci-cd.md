# CI/CD Pipeline

This repository uses GitHub Actions for the review and rollout path:

- `Lint` runs on pull requests and invokes Super-Linter against changed files
  with advisory status reporting. It is the shared lightweight lint signal for
  every PR; the repository-specific blocking checks remain in `Terragrunt Plan`
  and `validate`.
- `Terragrunt Plan` runs on pull requests. It always runs static checks and
  Checkov first. Trusted same-repository pull requests then inspect the changed
  paths. If the change touches `IaC/**`, flake inputs, OpenTofu/Terragrunt
  policy inputs, or live-plan helper scripts, the job connects to Octelium, runs
  a live Terragrunt plan, and updates the managed plan section in the PR
  description. Manifest-only, workflow-only, and docs-only changes skip the
  Octelium/Kubernetes/OpenTofu live-plan steps but still run rendered Conftest
  policies and replace the managed PR plan section with an explicit skip note.
  Forked pull requests run Conftest after the live plan skip notice.
- `Terragrunt Apply` runs after changes land on `main` and can also be started
  manually with `workflow_dispatch`. It repeats static checks and Conftest
  before connecting to Octelium and applying the live Terragrunt phases in
  order: Argo CD bootstrap, SSM parameter declarations, Entra application
  registrations, Argo CD Application registrations, and Kubernetes secret
  materialization.

Forked pull requests never receive AWS, Octelium, or Kubernetes secrets. They
run the static checks and Conftest only.

## Monitoring

Grafana owns the repository dashboard for the GitHub review path. The
`GitHub PR Status` dashboard in `clusters/homelab/apps/grafana` uses the
provisioned `GitHub` Infinity datasource to query public GitHub REST API
endpoints for open pull requests, pull requests with failing or pending status
checks, and recent failed workflow runs.

The GitHub dashboard can show recent failed workflow runs through the public
GitHub REST API. Grafana-managed GitHub Actions alert rules are intentionally
not provisioned while the datasource is unauthenticated, because shared public
API rate limits can turn the alert rules into noisy datasource-error pages.
Re-enable those alerts only after adding a reviewed token-backed secret
contract for Grafana.

## Security Model

- Workflows use `pull_request` and `push`; they do not use
  `pull_request_target`.
- The lint workflow is a lightweight changed-file gate that preserves the
  required `Lint` status context without replacing the repository's stricter
  static and Terragrunt gates. It checks diff whitespace, parses changed YAML
  files, runs `bash -n` on changed shell scripts, and uses workflow concurrency
  to cancel stale lint runs for the same pull request.
- Policy Bot reads this repository's `.policy.yml` and requires every pull
  request commit to have a GitHub-verified signature before normal review
  approval can satisfy the `policy-bot: main` branch protection check. The
  explicit comment path accepts only a `👍` comment from `rstuhlmuller`,
  including PRs opened by `rodman` and PRs where `rstuhlmuller` authored or
  committed changes; it does not read PR body text or other users' comments.
  The organization-member approval rule also opts into author and contributor
  approvals so matching Stuhlmuller approvals are not ignored as disqualified.
- External GitHub Actions are pinned to full commit SHAs and checked by
  Conftest.
- The Terragrunt plan and apply workflows restore and save a GitHub Actions
  cache for the Nix store after Nix is installed and before the first
  `nix develop --command ...` step. The cache key is derived from the runner OS,
  `flake.nix`, and `flake.lock`, with an OS-scoped fallback so dependency
  updates can still reuse the nearest previous dev shell closure.
- GitHub token permissions default to none. Jobs opt in to `contents: read`;
  live Terragrunt jobs request `id-token: write`; and the trusted PR plan job
  requests `pull-requests: write` only so it can refresh the managed plan
  section in the PR description after a successful plan.
- AWS access uses GitHub OIDC and short-lived role sessions. Do not add static
  AWS access keys to this repository.
- Octelium access uses a workload credential for User `homelab-ci` and Service
  `kubernetes-api.ci`. GitHub-hosted runners use sudo-backed TUN mode, allow
  Octelium DNS for Service publishing, force Octelium's `quicv0` tunnel mode,
  publish the Service to `127.0.0.1:16443`, and rely on the
  `homelab-ci-kubernetes-api-access` policy as the hard access boundary.
  Trusted pull requests only open this live access path when the diff includes
  IaC, flake, OpenTofu/Terragrunt policy, or live-plan helper inputs.
  Reconcile the `_gw-*` gateway AAAA records with
  `scripts/octelium-gateway-dns.sh` whenever Octelium gateway status changes;
  GitHub-hosted runners need those exact public gateway hostnames for the
  client dataplane.
- The kubeconfig is injected only from GitHub environment secrets and written to
  `$HOME/.kube/config` with mode `0600`. After writing it, CI rewrites the
  current cluster server to `https://127.0.0.1:16443` and sets the TLS server
  name to `10.1.0.199`, so the Kubernetes API certificate remains valid through
  the Octelium tunnel.
- Kubernetes reachability is verified first with a TLS reachability `curl`
  probe against `https://127.0.0.1:16443/version`, which may return `401` on
  clusters that reject anonymous API requests, and then with authenticated
  `kubectl --request-timeout=15s version` after kubeconfig installation.
- Plans are not uploaded as artifacts because Terraform/OpenTofu plans can
  include sensitive state context. Trusted same-repository PR plans render the
  saved `plan.out` files with `terragrunt show -no-color plan.out` and replace
  the managed `<!-- terragrunt-plan:start -->` section in the PR description
  after every successful plan. Trusted PRs that do not require a live plan
  replace that same managed section with a skip note so stale plan output is not
  left behind after a force-push or scope reduction.
- Automatic PR plans intentionally skip `IaC/live/aws-ssm-parameters` because
  that unit refreshes managed KMS, IAM, and SSM resources that require the
  protected production apply role. They also skip `IaC/live/kubernetes-secrets`
  because that unit reads decrypted AWS SSM parameters.
- Validation and deployment workflows use Terragrunt commands as their repo
  entrypoints. Terragrunt logs may still show `tofu:` prefixes or a
  `Failed to execute "tofu ..."` line because Terragrunt shells out to
  OpenTofu internally; do not copy those cache-directory commands as the
  operator recovery path.
- Terragrunt plan and apply phases use `--filter-affected` so only units
  changed between `main` and `HEAD` are queued. In CI, the helper script
  prepares the local `main` ref for that comparison: pull request plans compare
  against the PR base branch, while push applies compare against the previous
  `main` SHA from the GitHub event. Manual apply dispatches compare against
  `HEAD^`.
- Deleted Terragrunt units are handled separately because the current checkout
  no longer contains the directory that owns their state. The plan and apply
  scripts diff the base and head refs for deleted `IaC/**/terragrunt.hcl`
  files, create temporary empty Terragrunt units at those deleted paths, and
  reuse `IaC/root.hcl` so `path_relative_to_include()` points each fake unit at
  the original backend key. Pull request plans list the remote-state resources
  and save a destroy plan without rendering potentially sensitive values.
  Production apply lists the same state resources, applies the saved destroy
  plan, and then continues with the current checkout.
- The protected post-merge apply runs the production phases explicitly:
  destroy resources from deleted Terragrunt unit state, bootstrap Argo CD, apply
  SSM parameter declarations, apply Entra application registrations, apply Argo
  CD Application registrations serially, and finally materialize Kubernetes
  Secrets from SSM. Stack-wide apply phases use Terragrunt's explicit
  `run --all --filter-affected --non-interactive -- apply ...` form so the run
  queue is accepted in Actions and OpenTofu flags such as `-auto-approve` are
  forwarded to OpenTofu instead of being parsed as Terragrunt CLI flags.

References:

- [GitHub OIDC with AWS](https://docs.github.com/en/actions/how-tos/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)
- [GitHub Actions workflow runs REST API](https://docs.github.com/en/rest/actions/workflow-runs)
- [GitHub issue and pull request search filters](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/filtering-and-searching-issues-and-pull-requests)
- [nix-community/cache-nix-action](https://github.com/nix-community/cache-nix-action)
- [Conftest](https://www.conftest.dev/)
- [Checkov GitHub Actions integration](https://www.checkov.io/4.Integrations/GitHub%20Actions.html)

## GitHub Configuration

Create two GitHub environments:

- `homelab-plan`: used by same-repository pull request plans. Keep this
  unapproved if trusted branch authors should get automatic plans, or add
  reviewers if every live plan should require a human gate.
- `homelab-production`: used by post-merge applies. Require reviewers and limit
  deployment branches to `main`.

Add `OCTELIUM_CI_AUTH_TOKEN` and `KUBE_CONFIG_B64` to both environments. Add
`AZUREAD_CLIENT_SECRET` to `homelab-production`; adding it to `homelab-plan`
lets trusted pull requests render AzureAD application plans, otherwise that PR
plan phase is skipped with a warning. Repository-level secrets also work, but
environment secrets are preferred so production credentials can have approval
rules and tighter rotation:

| Secret | Environment | Purpose |
|--------|-------------|---------|
| `OCTELIUM_CI_AUTH_TOKEN` | both | Octelium workload credential for User `homelab-ci`, used only to publish `kubernetes-api.ci` to the CI runner localhost endpoint. |
| `KUBE_CONFIG_B64` | both | Base64-encoded kubeconfig for the homelab cluster. |
| `AZUREAD_CLIENT_SECRET` | `homelab-production`; optional in `homelab-plan` | Microsoft Entra application secret used by the AzureAD provider during production applies and optional trusted PR plans. |

Add these environment variables. The workflows read each non-sensitive value
from a GitHub variable first and fall back to a secret with the same name, so
storing them as environment secrets also works when that is how the repository
has been configured:

| Variable | Environment | Purpose |
|----------|-------------|---------|
| `AWS_ROLE_TO_ASSUME_HOMELAB` | repository, `homelab-plan`, or `homelab-production` | AWS role used by trusted PR plans and protected post-merge applies. |
| `AZUREAD_CLIENT_ID` | `homelab-production`; optional in `homelab-plan` | Microsoft Entra application client ID used by the AzureAD provider. |
| `AZUREAD_TENANT_ID` | `homelab-production`; optional in `homelab-plan` | Microsoft Entra tenant ID used by the AzureAD provider. |

## Octelium CI Access Setup

The Octelium service catalog at `docs/examples/octelium/homelab-services.yaml`
defines:

- workload User `homelab-ci`;
- Policy `homelab-ci-kubernetes-api-access`;
- TCP Service `kubernetes-api.ci -> tcp://10.1.0.199:6443`.

Apply that catalog to the Octelium Cluster after the control plane, portal, and
API hostnames are reachable:

```sh
octeliumctl apply --domain stinkyboi.com docs/examples/octelium/homelab-services.yaml
```

Create the workload credential outside git and store the printed token as
`OCTELIUM_CI_AUTH_TOKEN` in both GitHub environments:

```sh
octeliumctl create cred \
  --domain stinkyboi.com \
  --user homelab-ci \
  --policy homelab-ci-kubernetes-api-access \
  homelab-ci
```

Rotate `OCTELIUM_CI_AUTH_TOKEN` on suspicious runs, after runner image changes,
and on a regular schedule. The workflow still needs `KUBE_CONFIG_B64`; Octelium
only carries the transport path to the Kubernetes API.

Do not add `--scope` flags to `scripts/ci/connect-octelium.sh` for this
credential unless a newer Octelium release validates that scoped auth-token
sessions can publish `kubernetes-api.ci`. On Octelium v0.35, the
policy-bound workload credential authenticates and is then constrained by the
attached policy; adding `api:*` or `service:*` scopes causes the client session
to be denied before the runner can establish the tunnel.

## AWS Setup

The workflows use `AWS_ROLE_TO_ASSUME_HOMELAB` for both trusted PR plans and
protected post-merge applies. That role should trust GitHub OIDC only for this
repository and the expected environment subjects:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<account-id>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": [
            "repo:Stuhlmuller/homelab:environment:homelab-plan",
            "repo:Stuhlmuller/homelab:environment:homelab-production"
          ]
        }
      }
    }
  ]
}
```

Because the same role is used for apply, it must have write permissions for the
resources represented under `IaC/`, including S3 state lock writes and OpenTofu
state encryption access to `alias/homelab-opentofu` in the state region
(`us-east-1`). Required state-key permissions include `kms:Decrypt`,
`kms:DescribeKey`, `kms:Encrypt`, `kms:GenerateDataKey`, and
`kms:ReEncrypt*`.

It also needs runtime-secret KMS access for `IaC/live/aws-ssm-parameters`. That
unit manages SecureString parameters in `us-west-2` and creates a regional KMS
key using the same alias, `alias/homelab-opentofu`, for the SSM parameters. The
production apply role needs identity-based KMS permissions on the resolved
`us-west-2` key ARN as well as the state key in `us-east-1`. At minimum, an
existing-key refresh needs `kms:DescribeKey`; normal SSM declaration applies
also need the key, alias, IAM, and SSM write actions represented by
`IaC/live/aws-ssm-parameters`, plus the AWS SSM writes generated by
`IaC/live/azuread-applications/grafana`.

If the production apply fails while reading a KMS key in `us-west-2` with an
error like `AccessDeniedException` for `kms:DescribeKey`, update the identity
policy attached to `AWS_ROLE_TO_ASSUME_HOMELAB` through the approved AWS IAM
management path. Do not repair this by editing SSM parameter values, changing
External Secrets, or patching live cluster resources; the failure happens before
Terragrunt can refresh the SSM declaration state.

The Microsoft Entra provider uses the `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, and
`ARM_TENANT_ID` environment variables mapped from the protected GitHub
environment values above. Keep those credentials scoped to the homelab Entra
application registration workflow. Trusted pull request plans render the
AzureAD stack only when the credentials are configured in `homelab-plan`; the
production apply script applies that stack when the credentials are configured
in `homelab-production`. When they are not configured, production apply skips
that phase only if the push did not change the AzureAD stack; AzureAD stack
changes and manual dispatches require the credentials so identity drift is not
silently ignored.

## Local Equivalents

Run the same checks locally through the Nix shell:

```sh
nix develop --command pre-commit run --all-files
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/terragrunt-plan.sh
nix develop --command bash scripts/ci/conftest-policies.sh
```

The local pre-commit run is the closest repository-owned equivalent to the
Super-Linter PR check; GitHub Actions remains the source for the exact
Super-Linter status contexts.

The PR plan script intentionally skips the privileged SSM declaration and
Kubernetes secret materialization stacks. To review those locally, assume the
production apply role, install the kubeconfig, and run a focused
`terragrunt plan` from the stack directory.

The local scripts rely on your current `main` ref for Terragrunt's
`--filter-affected` comparison. Update `main` first when you want local output
to match the GitHub pull request or push diff. Deleted-unit detection uses the
same comparison base; set `TERRAGRUNT_FILTER_BASE_SHA` and
`TERRAGRUNT_FILTER_HEAD_SHA` when reproducing an exact GitHub run locally.

Set `TERRAGRUNT_PLAN_MARKDOWN=/path/to/terragrunt-plan.md` when running the PR
plan script locally if you want the same rendered `plan.out` markdown that the
workflow writes into pull request descriptions.

Only run apply after the same validation has passed and the change has been
reviewed:

```sh
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/conftest-policies.sh
nix develop --command bash scripts/ci/terragrunt-apply.sh
```

Manual apply dispatches compare against `HEAD^`; use the normal post-merge push
path when the affected-unit range needs to span multiple commits.
