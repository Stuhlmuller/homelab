# CI/CD Pipeline

This repository uses GitHub Actions for the review and rollout path:

- `Terragrunt Plan` runs on pull requests. It always runs static checks and
  Checkov first. Trusted same-repository pull requests then connect to the
  tailnet, run a live Terragrunt plan, and run Conftest policies after the plan
  step. Forked pull requests run Conftest after the live plan skip notice.
- `Terragrunt Apply` runs after changes land on `main` and can also be started
  manually with `workflow_dispatch`. It repeats static checks and Conftest
  before connecting to the tailnet and applying the live Terragrunt phases in
  order: Argo CD bootstrap, SSM parameter declarations, Entra application
  registrations, Argo CD Application registrations, and Kubernetes secret
  materialization.

Forked pull requests never receive AWS, Tailscale, or Kubernetes secrets. They
run the static checks and Conftest only.

## Security Model

- Workflows use `pull_request` and `push`; they do not use
  `pull_request_target`.
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
- Tailscale access uses an auth key because this tailnet has tailnet lock
  enabled and the federated identity path is not available for these runners.
  Keep the key ephemeral, reusable only if operationally required, pre-approved
  for tailnet lock, and scoped to the CI tags documented below.
- The kubeconfig is injected only from GitHub environment secrets and written to
  `$HOME/.kube/config` with mode `0600`.
- The workflow does not use the Tailscale action's built-in `ping` input for
  subnet-routed cluster addresses. Kubernetes reachability is verified with
  `kubectl --request-timeout=15s version` after kubeconfig installation.
- After the Tailscale client authenticates, the workflow runs
  `tailscale set --accept-routes=true` so it can use the subnet route to the
  Kubernetes API endpoint without conflicting with the action's own login
  flags.
- The workflow relies on the repo-owned `homelab-exit-node` connector's
  advertised `10.1.0.199/32` subnet route for Kubernetes API access. It does
  not select the connector as a full exit node, so public AWS STS/KMS calls keep
  using the GitHub-hosted runner's normal network path and DNS resolver.
- Plans are not uploaded as artifacts because Terraform/OpenTofu plans can
  include sensitive state context. Trusted same-repository PR plans render the
  saved `plan.out` files with `terragrunt show -no-color plan.out` and replace
  the managed `<!-- terragrunt-plan:start -->` section in the PR description
  after every successful plan.
- Automatic PR plans intentionally skip `IaC/live/aws-ssm-parameters` because
  that unit refreshes managed KMS, IAM, and SSM resources that require the
  protected production apply role. They also skip `IaC/live/kubernetes-secrets`
  because that unit reads decrypted AWS SSM parameters.
- The protected post-merge apply runs the production phases explicitly:
  bootstrap Argo CD, apply SSM parameter declarations, apply Entra application
  registrations, apply Argo CD Application registrations serially, and finally
  materialize Kubernetes Secrets from SSM. Stack-wide apply phases use
  Terragrunt's explicit `run --all --non-interactive -- apply ...` form so the
  run queue is accepted in Actions and OpenTofu flags such as `-auto-approve`
  are forwarded to OpenTofu instead of being parsed as Terragrunt CLI flags.

References:

- [Tailscale GitHub Action](https://tailscale.com/docs/integrations/github/github-action)
- [Tailscale grants syntax](https://tailscale.com/docs/reference/syntax/grants)
- [GitHub OIDC with AWS](https://docs.github.com/en/actions/how-tos/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)
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

Add `TS_AUTH_KEY` and `KUBE_CONFIG_B64` to both environments. Add
`AZUREAD_CLIENT_SECRET` to `homelab-production`. Repository-level secrets also
work, but environment secrets are preferred so production credentials can have
approval rules and tighter rotation:

| Secret | Environment | Purpose |
|--------|-------------|---------|
| `TS_AUTH_KEY` | both | Tailscale auth key allowed by tailnet lock and scoped to the CI runner tags. |
| `KUBE_CONFIG_B64` | both | Base64-encoded kubeconfig for the homelab cluster. |
| `AZUREAD_CLIENT_SECRET` | `homelab-production` | Microsoft Entra application secret used by the AzureAD provider during production applies. |

Add these environment variables. The workflows read each non-sensitive value
from a GitHub variable first and fall back to a secret with the same name, so
storing them as environment secrets also works when that is how the repository
has been configured:

| Variable | Environment | Purpose |
|----------|-------------|---------|
| `AWS_ROLE_TO_ASSUME_HOMELAB` | repository, `homelab-plan`, or `homelab-production` | AWS role used by trusted PR plans and protected post-merge applies. |
| `AZUREAD_CLIENT_ID` | `homelab-production` | Microsoft Entra application client ID used by the AzureAD provider. |
| `AZUREAD_TENANT_ID` | `homelab-production` | Microsoft Entra tenant ID used by the AzureAD provider. |

## Tailscale Setup

Use separate tags for plan and apply runners:

- `tag:github-actions-terragrunt-plan`
- `tag:github-actions-terragrunt-apply`

Create one Tailscale auth key that tailnet lock can admit. The key should be
ephemeral, pre-approved for tailnet lock, and restricted to the CI tags when the
admin panel permits tag scoping. In the tailnet policy, grant those tags only
the cluster API path they need.

The repository-owned `homelab-exit-node` Connector is tagged `tag:k8s`, acts as
the current bootstrap exit node, and advertises `10.1.0.199/32` as the
dedicated Kubernetes API route. Auto-approve the narrow route for `tag:k8s`
when possible, and use grants to keep CI access limited to the API endpoint and
port:

```json
{
  "autoApprovers": {
    "exitNode": ["tag:k8s"],
    "routes": {
      "10.1.0.199/32": ["tag:k8s"]
    }
  },
  "tagOwners": {
    "tag:github-actions-terragrunt-plan": ["autogroup:admin"],
    "tag:github-actions-terragrunt-apply": ["autogroup:admin"],
    "tag:k8s": ["tag:k8s-operator"]
  },
  "grants": [
    {
      "src": ["tag:github-actions-terragrunt-plan"],
      "dst": ["10.1.0.199/32"],
      "ip": ["tcp:6443"],
      "via": ["tag:k8s"]
    },
    {
      "src": ["tag:github-actions-terragrunt-apply"],
      "dst": ["10.1.0.199/32"],
      "ip": ["tcp:6443"],
      "via": ["tag:k8s"]
    }
  ]
}
```

If the bootstrap exit-node fallback needs a broader `autogroup:internet` grant
to be selectable, treat it as temporary and keep it limited to the two CI tags
and the `tag:k8s` route path. Do not grant `tag:github-actions-terragrunt-*`
broad tailnet or SSH access unless a later repository change documents the
requirement. Rotate `TS_AUTH_KEY` on any failed or suspicious run, after runner
image changes, and on a regular schedule.

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
environment values above. Keep those credentials scoped to the Grafana Entra
application workflow. The production apply script applies
`IaC/live/azuread-applications` when those credentials are configured. When they
are not configured, it skips that phase only if the push did not change the
AzureAD stack; AzureAD stack changes and manual dispatches require the
credentials so identity drift is not silently ignored.

## Local Equivalents

Run the same checks locally through the Nix shell:

```sh
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/terragrunt-plan.sh
nix develop --command bash scripts/ci/conftest-policies.sh
```

The PR plan script intentionally skips the privileged SSM declaration and
Kubernetes secret materialization stacks. To review those locally, assume the
production apply role, install the kubeconfig, and run a focused
`terragrunt plan` from the stack directory.

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
