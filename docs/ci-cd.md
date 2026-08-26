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
  materialization. A run compares against the latest successful
  `Terragrunt Apply` SHA so a failed run's unapplied changes remain in the next
  affected-unit range.

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
  static and Terragrunt gates. It runs the upstream Super-Linter action with
  `VALIDATE_ALL_CODEBASE=false` and uses workflow concurrency to cancel stale
  lint runs for the same pull request.
- Policy Bot reads this repository's `.policy.yml` and requires every pull
  request commit to have a GitHub-verified signature before normal review
  approval can satisfy the `policy-bot: main` branch protection check. The
  Codex path accepts only the exact top-level `👍` comment from
  `chatgpt-codex-connector[bot]` that `AGENTS.md` requires after a passing
  review with no P0 or P1 alerts. A later push invalidates that approval, so
  auto-merge remains queued until Policy Bot observes the pass signal for the
  latest changes. The human comment path accepts only a `👍` comment from
  `rstuhlmuller`, including PRs opened by `rodman` and PRs where `rstuhlmuller`
  authored or committed changes; it does not read PR body text or other users'
  comments. The organization-member approval rule also opts into author and
  contributor approvals so matching Stuhlmuller approvals are not ignored as
  disqualified.
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
- Octelium access uses an access-token credential for workload User `homelab-ci`
  and the public clientless `KUBERNETES` Service `kubernetes-api-ci`. Live
  Terragrunt and diagnostic jobs run on GitHub-hosted Ubuntu and use the
  existing Cloudflare Tunnel endpoint at `https://kubernetes-api-ci.stinkyboi.com`.
  This avoids the IPv6-only Gateway QUIC path, while the
  `homelab-ci-kubernetes-api-access` policy remains the hard access boundary.
  The dedicated User gives both its clientless session and access token a
  30-day lifetime; rotate the credential every 21 days.
  Trusted pull requests only open this live access path when the diff includes
  IaC, flake, OpenTofu/Terragrunt policy, or live-plan helper inputs.
- The upstream kubeconfig is stored only as the Octelium Secret
  `homelab-ci-kubeconfig`, materialized with
  `scripts/octelium-ci-kubeconfig-secret.sh`; it is never committed or injected
  into GitHub. CI writes a token-only kubeconfig with mode `0600`, then verifies
  the Kubernetes API with authenticated `kubectl`.
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
  changed between the selected base and `HEAD` are queued. Pull request plans
  compare against the PR base branch. Production applies query the latest
  successful `Terragrunt Apply` run and use its `head_sha`, including manual
  dispatches. When that run is absent, unavailable, or not an ancestor of the
  current `main`, the workflow fails closed because it cannot safely infer which
  removed units need retirement.
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

Add `OCTELIUM_CI_AUTH_TOKEN` to both environments. Add
`AZUREAD_CLIENT_SECRET` to `homelab-production`; adding it to `homelab-plan` lets
trusted pull requests render AzureAD application plans, otherwise that PR plan
phase is skipped with a warning. Repository-level secrets also work, but
environment secrets are preferred so production credentials can have approval
rules and tighter rotation:

| Secret | Environment | Purpose |
| --- | --- | --- |
| `OCTELIUM_CI_AUTH_TOKEN` | both | Octelium clientless access token for User `homelab-ci`, scoped to the public `kubernetes-api-ci` Service. |
| `AZUREAD_CLIENT_SECRET` | `homelab-production`; optional in `homelab-plan` | Microsoft Entra application secret used by the AzureAD provider during production applies and optional trusted PR plans. |

The retired `/homelab/github-actions-runner/registration-token` SSM parameter
has no runtime consumer. Its declaration and preexisting-parameter adoption
guard remain temporarily because the production policy rejects SSM parameter
deletion; remove both only with a reviewed repository-owned state and
secret-retirement workflow.

Add these environment variables. The workflows read each non-sensitive value
from a GitHub variable first and fall back to a secret with the same name, so
storing them as environment secrets also works when that is how the repository
has been configured:

| Variable | Environment | Purpose |
| --- | --- | --- |
| `AWS_ROLE_TO_ASSUME_HOMELAB` | repository, `homelab-plan`, or `homelab-production` | AWS role used by trusted PR plans and protected post-merge applies. |
| `AZUREAD_CLIENT_ID` | `homelab-production`; optional in `homelab-plan` | Microsoft Entra application client ID used by the AzureAD provider. |
| `AZUREAD_TENANT_ID` | `homelab-production`; optional in `homelab-plan` | Microsoft Entra tenant ID used by the AzureAD provider. |

## Octelium CI Access Setup

The normal plan and apply path must keep using `OCTELIUM_CI_AUTH_TOKEN` and the
clientless `kubernetes-api-ci` Service. Do not add kubeconfig material to the
normal plan or apply jobs.

GitHub-hosted runners have no independent route to the private Kubernetes API.
`Break Glass NOFX Recovery` also installs its kubeconfig through Octelium, so it
cannot repair an Octelium outage and does not consume a repository kubeconfig
secret.

When recovery requires the committed `kubernetes-node-labels` state while
Octelium is unavailable, use a reviewed `main` checkout on a trusted LAN
machine whose operator kubeconfig points directly at the canonical API
endpoint. Apply only that unit through its normal Terragrunt state and provider
path:

```sh
nix develop --command aws sso login --profile default

nix develop --command bash <<'EOF'
set -euo pipefail

test "$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')" = \
  "https://10.1.0.199:6443"
kubectl --request-timeout=15s version

(cd IaC && terragrunt stack generate)
cd IaC/live/kubernetes-node-labels
rm -f plan.out plan.json
terragrunt --log-disable init -reconfigure -no-color
terragrunt plan -out=plan.out -no-color
terragrunt --log-disable show -json plan.out >plan.json
conftest test --policy ../../../policy --output github plan.json
terragrunt apply -no-color plan.out
EOF
```

The AWS CLI `default` profile needs access to the shared S3/KMS state backend.
The kubeconfig must remain only on the trusted LAN machine. After Octelium is
healthy, rerun the normal protected `Terragrunt Apply` workflow to reconcile
the complete affected range. Use `Break Glass NOFX Recovery` only for its
narrower NOFX reconciliation after the Octelium Kubernetes route works again.

The Octelium service catalog at `docs/examples/octelium/homelab-services.yaml`
defines:

- workload User `homelab-ci` with matching 30-day clientless-session and
  access-token lifetimes;
- Policy `homelab-ci-kubernetes-api-access`, which allows only the public
  clientless Kubernetes Service;
- public `KUBERNETES` Service `kubernetes-api-ci -> https://10.1.0.199:6443`.

Apply that catalog after materializing the upstream kubeconfig Secret, then
create or rotate the GitHub environment secret in both CI environments:

```sh
scripts/octelium-ci-kubeconfig-secret.sh --kubeconfig ~/.kube/config
scripts/octelium-ci-credential.sh
```

The helper requires an authenticated Octelium admin session for `octeliumctl`
and GitHub CLI access to `Stuhlmuller/homelab`. It applies the catalog, creates
or rotates the `homelab-ci` credential, pipes the generated token directly into
the `OCTELIUM_CI_AUTH_TOKEN` secret for `homelab-plan` and
`homelab-production`, and removes the temporary token file before exit.
For existing credentials, the helper verifies GitHub environment secret write
access by writing and deleting a temporary preflight secret, reconciles the
credential binding to User `homelab-ci` and Policy
`homelab-ci-kubernetes-api-access`, deletes every Session for that dedicated
User so Octelium cannot reuse its old expiry, then rotates the token. It
refuses to rotate an existing credential when GitHub secret updates are
disabled, because that would invalidate the old CI token without storing the
replacement.
Run rotation in a quiet window: deleting the old Session invalidates the
current bearer before the two GitHub environment secrets are updated. After
token generation, the helper retries each secret write until both environments
hold the replacement; if interrupted, rerun the helper.
When recovering through a temporary Octelium CLI session, pass that session
directory with `--homedir /tmp/octelium-admin`. If the public Octelium API path
is not carrying authenticated admin CLI calls reliably, point `--octelium-proxy`
at a local CONNECT proxy that forwards `octelium-api.stinkyboi.com:443` to the
in-cluster Istio gateway.

Avoid running raw `octeliumctl create cred` in shared terminals or CI logs
because it can print the generated token. If the helper cannot reach GitHub,
fix `gh auth status` or the target environment permissions, then rerun the
helper so the token is captured and stored without being displayed.

Rotate `OCTELIUM_CI_AUTH_TOKEN` every 21 days, on suspicious runs, after catalog
policy changes, and after runner image changes. Reconcile the
Octelium kubeconfig Secret when the upstream Kubernetes credential changes. If
CI receives Octelium `401` from authenticated `kubectl` against
`kubernetes-api-ci`, reapply the catalog and rotate the credential with
`scripts/octelium-ci-credential.sh`. Treat `403` as a policy or User-state
failure before rotating. Reconcile the upstream kubeconfig Secret when its
Kubernetes credential changes.
If the credential must be recovered, apply the recovery catalog and use its
distinct User, Policy, and credential name:

```sh
octeliumctl apply --domain stinkyboi.com docs/examples/octelium/homelab-ci-recovery.yaml
scripts/octelium-ci-credential.sh \
  --skip-catalog \
  --user homelab-ci-recovery \
  --credential-name homelab-ci-recovery \
  --policy ci-recovery-access
```

The helper updates the same GitHub environment secrets. The recovery user is
limited to the same public Kubernetes Service, but its default clientless
Session expires after two hours. Before then, restore the primary credential,
verify both GitHub environments, and remove the temporary recovery resources:

```sh
scripts/octelium-ci-credential.sh --homedir /tmp/octelium-admin

primary_sha="$(gh api repos/Stuhlmuller/homelab/commits/main --jq .sha)"
gh workflow run homelab-diagnostics.yml --ref main
gh workflow run terragrunt-apply.yml --ref main
gh run list --workflow homelab-diagnostics.yml --commit "$primary_sha" --event workflow_dispatch --limit 1 --json status,conclusion,url --jq '.[0]'
gh run list --workflow terragrunt-apply.yml --commit "$primary_sha" --event workflow_dispatch --limit 1 --json status,conclusion,url --jq '.[0]'
```

Repeat the two `gh run list` commands until both report `completed` and
`success`, then clean up:

```sh
scripts/octelium-ci-credential.sh \
  --homedir /tmp/octelium-admin \
  --skip-catalog \
  --user homelab-ci-recovery \
  --delete-user-sessions-only
octeliumctl --homedir /tmp/octelium-admin delete credential homelab-ci-recovery --domain stinkyboi.com
octeliumctl --homedir /tmp/octelium-admin delete user homelab-ci-recovery --domain stinkyboi.com
octeliumctl --homedir /tmp/octelium-admin delete policy ci-recovery-access --domain stinkyboi.com
```

## AWS Setup

The workflows use `AWS_ROLE_TO_ASSUME_HOMELAB` for both trusted PR plans and
protected post-merge applies. The operator unit owns the role trust and permits
only the two homelab environments plus the active `github-iac` pull-request and
`main` workflows:

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
            "repo:Stuhlmuller/github-iac:pull_request",
            "repo:Stuhlmuller/github-iac:ref:refs/heads/main",
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

The additive IAM grant required to manage the chunked SSM reader policies is
declared in `IaC/operator/github-actions-role-policy`. It is deliberately
outside the GitHub workflow traversal: an automation role must not be able to
widen or replace the policy attached to itself. After review, an AWS
administrator applies that unit through Terragrunt:

```sh
aws sso login --profile <administrator-profile>
cd IaC/operator/github-actions-role-policy
terragrunt --log-disable init -backend=false -lockfile=readonly -no-color
terragrunt --log-disable validate -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable init -reconfigure -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable state list
```

Before the first plan, import the existing GitHub Actions role and External
Secrets user when their state addresses are absent. Do not repeat an import
after its address is present:

```sh
AWS_PROFILE=<administrator-profile> terragrunt --log-disable import \
  'aws_iam_role.github_actions' Github-TF-State
AWS_PROFILE=<administrator-profile> terragrunt --log-disable import \
  'aws_iam_user.external_secrets' external-secrets_aws-ssm-auth
```

Then save, review, and apply the same plan:

```sh
AWS_PROFILE=<administrator-profile> terragrunt --log-disable plan -out=plan.out -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable show -no-color plan.out
AWS_PROFILE=<administrator-profile> terragrunt --log-disable apply -no-color plan.out
```

The resulting managed policy is limited to lifecycle operations on the ten
exact slots `homelab-ssm-parameter-reader-00` through `-09` and conditioned
attach/detach operations on the exact `homelab-ssm-parameter-readers` group;
attachment listing is read-only on that same group.

The unit also adopts the existing `external-secrets_aws-ssm-auth` IAM user,
removes direct managed and inline user policies, and attaches an operator-owned
permissions boundary. That boundary caps effective access at
`ssm:GetParameter`/`ssm:GetParameters` under `/homelab/*` plus decrypt/describe
access on the regional runtime-secret KMS key. This keeps the existing group
management path from becoming an indirect route to unrelated AWS permissions.

A production failure that reports
`AccessDenied` for `iam:CreatePolicy` means this operator prerequisite has not
been applied or has drifted; repair it through this unit, then rerun the failed
`Terragrunt Apply` workflow.

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
error like `AccessDeniedException` for `kms:DescribeKey`, update the relevant
operator-owned identity policy through a reviewed Terragrunt unit. Do not repair
this by editing SSM parameter values, changing External Secrets, or patching live
cluster resources; the failure happens before Terragrunt can refresh the SSM
declaration state.

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

Every production apply, including manual dispatch, compares against the latest
successful `Terragrunt Apply` SHA. Rerunning after one or more failed applies
therefore keeps the full unapplied range instead of considering only the newest
commit.
