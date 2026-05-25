# CI/CD Pipeline

This repository uses GitHub Actions for the review and rollout path:

- `Terragrunt Plan` runs on pull requests. It always runs static checks,
  Conftest policies, and Checkov. Trusted same-repository pull requests also
  connect to the tailnet and run a live Terragrunt plan.
- `Terragrunt Apply` runs after changes land on `main` and can also be started
  manually with `workflow_dispatch`. It repeats static checks before connecting
  to the tailnet and applying the live Terragrunt stack.

Forked pull requests never receive AWS, Tailscale, or Kubernetes secrets. They
run the static checks only.

## Security Model

- Workflows use `pull_request` and `push`; they do not use
  `pull_request_target`.
- External GitHub Actions are pinned to full commit SHAs and checked by
  Conftest.
- GitHub token permissions default to none. Jobs opt in to `contents: read`,
  and only the live Terragrunt jobs request `id-token: write`.
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
- The workflow also selects the repo-owned `homelab-exit-node` connector as a
  bootstrap path for the GitHub-hosted runner. The connector advertises a
  narrower `10.1.0.199/32` route for the Kubernetes API; prefer that route once
  it is approved in the tailnet.
- Plans are not uploaded as artifacts because Terraform/OpenTofu plans can
  include sensitive state context.
- Automatic PR plans intentionally skip `IaC/live/kubernetes-secrets` because
  that unit reads decrypted AWS SSM parameters. The protected post-merge apply
  runs the full `IaC/live` stack.

References:

- [Tailscale GitHub Action](https://tailscale.com/docs/integrations/github/github-action)
- [Tailscale grants syntax](https://tailscale.com/docs/reference/syntax/grants)
- [GitHub OIDC with AWS](https://docs.github.com/en/actions/how-tos/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)
- [Conftest](https://www.conftest.dev/)
- [Checkov GitHub Actions integration](https://www.checkov.io/4.Integrations/GitHub%20Actions.html)

## GitHub Configuration

Create two GitHub environments:

- `homelab-plan`: used by same-repository pull request plans. Keep this
  unapproved if trusted branch authors should get automatic plans, or add
  reviewers if every live plan should require a human gate.
- `homelab-production`: used by post-merge applies. Require reviewers and limit
  deployment branches to `main`.

Add these secrets to both environments. Repository-level secrets also work, but
environment secrets are preferred so production credentials can have approval
rules and tighter rotation:

| Secret | Purpose |
|--------|---------|
| `TS_AUTH_KEY` | Tailscale auth key allowed by tailnet lock and scoped to the CI runner tags. |
| `KUBE_CONFIG_B64` | Base64-encoded kubeconfig for the homelab cluster. |

Add these environment variables:

| Variable | Environment | Purpose |
|----------|-------------|---------|
| `AWS_ROLE_TO_ASSUME_HOMELAB` | repository or `homelab-plan` | AWS role used by PR plans. |
| `AWS_TERRAGRUNT_APPLY_ROLE_ARN` | workflow env | Pinned to `arn:aws:iam::716182248480:role/Github-Actions-IDP` for post-merge applies. |

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

Use separate IAM roles for plan and apply. Both roles should trust GitHub OIDC
only for this repository and the expected environment subject:

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
          "token.actions.githubusercontent.com:sub": "repo:Stuhlmuller/homelab:environment:homelab-production"
        }
      }
    }
  ]
}
```

Use `repo:Stuhlmuller/homelab:environment:homelab-plan` for the plan role.
The plan role should have the narrowest read access that lets OpenTofu refresh
state and create state lock files. The apply workflow assumes
`arn:aws:iam::716182248480:role/Github-Actions-IDP`; that role needs the write
permissions for the resources represented under `IaC/`.

## Local Equivalents

Run the same checks locally through the Nix shell:

```sh
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/terragrunt-plan.sh
```

Only run apply after the same validation has passed and the change has been
reviewed:

```sh
nix develop --command bash scripts/ci/terragrunt-apply.sh
```
