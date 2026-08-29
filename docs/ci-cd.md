# CI/CD Pipeline

This repository uses GitHub Actions for the review and rollout path:

- `Lint` runs on pull requests and invokes Super-Linter against changed files
  with advisory status reporting. It is the shared lightweight lint signal for
  every PR; the repository-specific blocking checks remain in `Terragrunt Gate`
  and `validate`.
- `Terragrunt Plan` runs on every pull request. Its unprivileged static job
  detects live-plan scope, runs static checks, Checkov, and rendered Conftest
  policies. Only trusted same-repository changes to the plan workflow,
  `IaC/**`, flake inputs, OpenTofu/Terragrunt policy inputs, or live-plan helper
  scripts enter the protected `homelab-plan` environment, connect through
  Octelium, and run the live plan with details withheld. Other same-repository
  changes use a no-permission skip-check job;
  forks run only the static job.
  The always-present `Terragrunt Gate` succeeds only when static checks and
  every applicable live plan or skip-check job succeed.
- `Terragrunt Apply Request` runs after every change lands on `main`, cancels an
  older request check, and prints the exact current-SHA dispatch command plus
  links to active applies. It has no production environment, stored secrets,
  or OIDC permission.
- `Terragrunt Apply` starts only through `workflow_dispatch` with the exact
  current `main` SHA. It repeats static checks and Conftest, waits for the
  `homelab-production` approval, then verifies `main` again before referencing
  environment credentials or running live commands. Full applies run the Argo
  CD bootstrap, SSM parameter declarations, Entra application registrations,
  Argo CD Application registrations, and Kubernetes secret materialization.
  They compare against the latest successful historical push apply or full
  dispatch so failed or deferred changes remain in the next affected range;
  targeted Argo reconciliations never advance that checkpoint.
- `Octelium Private Kubernetes Apply` is a separate manual lane for only
  `Policy/homelab-private-kubernetes-access` and
  `Service/kubernetes-api.homelab`. It repeats the exact-`main` and production
  approval gates, never prunes, and proves a second apply has no live diff.

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
- External GitHub Actions are pinned to full commit SHAs, checked by Conftest,
  and rejected by the repository when a workflow references a mutable tag.
- The `main` ruleset requires pull requests, squash-only linear history,
  verified signatures, strict always-on checks, and blocks branch deletion and
  force pushes. The required checks are `policy-bot: main`, `Lint`, `repo`,
  `Analyze (python)`, `analyze-actions`, and `release-dry-run`. `Terragrunt Gate`
  is the stable candidate for merge-blocking Terragrunt validation; do not add
  it to ruleset `14700233` until a merged workflow revision has emitted the
  context for both a no-live-plan pull request and a trusted live-plan pull
  request.
- The Terragrunt plan and apply workflows restore and save a GitHub Actions
  cache for the Nix store after Nix is installed and before the first
  `nix develop --command ...` step. The cache key is derived from the runner OS,
  `flake.nix`, and `flake.lock`, with an OS-scoped fallback so dependency
  updates can still reuse the nearest previous dev shell closure.
- GitHub token permissions default to none. Jobs opt in to `contents: read`,
  and live Terragrunt jobs request `id-token: write`. No credentialed plan job
  can write to pull requests or another public GitHub surface.
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
  the plan workflow, IaC, flake, OpenTofu/Terragrunt policy, or live-plan helper
  inputs.
- The private Kubernetes catalog lane uses a different, one-authentication
  `AUTH_TOKEN` Credential. Octelium auto-deletes it when the job logs in; the
  unused Credential expires after 30 minutes, the resulting client Session
  lasts at most 15 minutes, and the job logs it out. Its highest-priority inline
  policy explicitly denies everything except List/Create/Update for Policy and
  Service.
  Octelium v0.35 cannot restrict those methods by object name, so the fixed
  extraction script, reviewed workflow hash, exact `main` SHA, and production
  approval are the object-level boundary.
- The upstream kubeconfig for both `kubernetes-api-ci` and the private
  `kubernetes-api.homelab` Service is stored only as the Octelium Secret
  `homelab-ci-kubeconfig`, materialized with
  `scripts/octelium-ci-kubeconfig-secret.sh`; it is never committed or injected
  into GitHub. The install helper writes a token-only kubeconfig with mode
  `0600`, then verifies Octelium upstream credential injection with
  `kubectl auth whoami`. Each Kubernetes live job gives every step a stable
  `id`. The whole-workflow fingerprint also locks display names so they cannot
  evaluate and expose a secret expression. Workflow policy hashes every job
  attached to `homelab-plan` or `homelab-production`, including plan, apply,
  diagnostics, and Cloudflare maintenance, plus the workflow trigger,
  permissions, concurrency, `env`, and run defaults. Any added action or
  command, changed execution condition, shell, working directory, job setting,
  or step payload fails closed. Environment names must be literal and are
  classified case-insensitively, matching GitHub. For the three Kubernetes
  jobs, `install_kubeconfig` alone receives the exact Octelium URL and
  `${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}` expression. The `live` step must
  inherit neither value, so workflow, job, and step override drift is rejected
  using GitHub's step-over-job-over-workflow environment precedence. Both steps
  withhold command output from public logs.

  The rotation helper validates and minifies one direct context with exactly
  one current embedded CA certificate before creating a new Secret. It never
  overwrites an active name, and both Octelium Service definitions keep
  upstream TLS verification enabled. Rotate through the staged catalog cutover
  in `docs/octelium.md`, then validate CI, operator, and Cordium access.
- Plans are not uploaded, printed, or copied into pull requests because
  Terraform/OpenTofu plans can include sensitive state context. Trusted
  same-repository jobs evaluate private plans with Conftest and delete them on
  exit. The required check is the only public plan result. Live plan, apply,
  diagnostic, and Cloudflare reconciliation output is also withheld from public
  Actions logs; reproduce failures from an approved local operator session.
  Workflow policy
  rejects direct live CLI output or reading the private log after the wrapper,
  and live credentials exist only on the exact step that consumes them. Static
  checks reject any new environment-, secret-, token-, or write-permission job
  until its complete normalized definition is reviewed and hashed. The
  pre-commit scan rejects plan/state filenames plus binary plans or JSON
  plan/state exports hidden behind arbitrary names.
- Automatic PR plans intentionally skip `IaC/live/aws-ssm-parameters` because
  that unit refreshes managed KMS, IAM, and SSM resources that require the
  protected production apply role. They also skip `IaC/live/kubernetes-secrets`
  because that unit reads decrypted AWS SSM parameters.
- Validation and deployment workflows use Terragrunt commands as their repo
  entrypoints. Terragrunt logs may still show `tofu:` prefixes or a
  `Failed to execute "tofu ..."` line because Terragrunt shells out to
  OpenTofu internally; do not copy those cache-directory commands as the
  operator recovery path.
- Application-registration and secret-materialization stack phases use
  explicit `--filter` expressions so only units changed between the selected
  base and `HEAD` are queued. Pull request plans compare against the PR base
  branch. Production applies use the latest successful historical push apply
  or dispatch whose run name starts with `Full @` as the checkpoint; targeted
  dispatches use `Targeted <app> @ <sha>` and never advance it. A targeted Argo
  dispatch instead plans and applies its exact named unit regardless of the
  affected range, then exits before unrelated phases. When that exact unit is
  confirmed tainted, the same
  protected dispatch may set `repair_argocd_app_state=true`; the workflow
  requires `argocd_app`, untaints only `kubernetes_manifest.this`, then runs the
  unchanged policy-checked plan and saved-plan apply. Any other repair value,
  missing target, or non-dispatch use fails closed. When the apply checkpoint is
  absent, unavailable, or not an ancestor of the current `main`, the workflow
  fails closed because it cannot safely infer which removed units need
  retirement.
- Deleted Terragrunt units are handled separately because the current checkout
  no longer contains the directory that owns their state. The plan and apply
  scripts diff the base and head refs for deleted `IaC/**/terragrunt.hcl`
  files, create temporary empty Terragrunt units at those deleted paths, and
  reuse `IaC/root.hcl` so `path_relative_to_include()` points each fake unit at
  the original backend key. Pull request plans list the remote-state resources
  and save a destroy plan without rendering potentially sensitive values.
  Production apply lists the same state resources, applies the saved destroy
  plan, and then continues with the current checkout.
- The protected full apply runs the production phases explicitly:
  destroy resources from deleted Terragrunt unit state, bootstrap Argo CD, apply
  SSM parameter declarations, apply Entra application registrations, apply Argo
  CD Application registrations serially, and finally materialize Kubernetes
  Secrets from SSM. Stack-wide apply phases use Terragrunt's explicit
  `run --all --filter ... --non-interactive -- apply ...` form so the run
  queue is accepted in Actions and OpenTofu flags such as `-auto-approve` are
  forwarded to OpenTofu instead of being parsed as Terragrunt CLI flags.

## Terragrunt Gate Ruleset Rollout

1. Merge the workflow change while `Terragrunt Gate` is not required.
2. From the merged `main` workflow, observe a same-repository PR with no live
   inputs: `Static Policy And Security Checks` and `Terragrunt Plan Skipped`
   must pass, `Terragrunt Plan` must be skipped, and `Terragrunt Gate` must pass.
3. Observe a trusted PR with live inputs: `Terragrunt Plan Skipped` must be
   skipped and `Terragrunt Gate` must remain blocked until the protected
   `Terragrunt Plan` succeeds. A fork must emit the gate without receiving the
   protected environment or a write token.
4. Add the exact `Terragrunt Gate` Actions context to ruleset `14700233` without
   changing its existing checks, then refresh a no-live-plan PR and confirm the
   strict ruleset does not deadlock.

References:

- [GitHub OIDC with AWS](https://docs.github.com/en/actions/how-tos/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)
- [GitHub Actions workflow runs REST API](https://docs.github.com/en/rest/actions/workflow-runs)
- [GitHub issue and pull request search filters](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/filtering-and-searching-issues-and-pull-requests)
- [nix-community/cache-nix-action](https://github.com/nix-community/cache-nix-action)
- [Conftest](https://www.conftest.dev/)
- [Checkov GitHub Actions integration](https://www.checkov.io/4.Integrations/GitHub%20Actions.html)

## GitHub Configuration

Create two GitHub environments:

- `homelab-plan`: used by same-repository pull request plans. Require a
  reviewer and approve only after reviewing the exact pull request diff; the
  job checks out pull request code before using live write-capable identities.
- `homelab-production`: used by post-merge applies. Require reviewers and limit
  deployment branches to `main`.

Add `OCTELIUM_CI_AUTH_TOKEN` to both environments. Add
`AZUREAD_CLIENT_SECRET` to `homelab-production`; adding it to `homelab-plan` lets
trusted pull requests render AzureAD application plans, otherwise that PR plan
phase is skipped with a warning. Keep live credentials environment-scoped so
GitHub withholds them until the required reviewer approves the job; do not keep
duplicate repository-scoped copies:

| Secret | Environment | Purpose |
| --- | --- | --- |
| `OCTELIUM_CI_AUTH_TOKEN` | both | Octelium clientless access token for User `homelab-ci`, scoped to the public `kubernetes-api-ci` Service. |
| `OCTELIUM_CATALOG_AUTH_TOKEN` | `homelab-production`, temporary | One-authentication token created immediately before the private Kubernetes catalog dispatch and removed immediately afterward. |
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
The targeted `Terragrunt Apply` dispatch also installs its kubeconfig through
Octelium, so it cannot repair an Octelium outage and does not consume a
repository kubeconfig secret.

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
kubectl --request-timeout=15s auth whoami

(cd IaC && terragrunt stack generate)
cd IaC/live/kubernetes-node-labels
umask 077
plan_dir="$(mktemp -d "${TMPDIR:-/tmp}/homelab-node-labels.XXXXXX")"
trap 'rm -rf -- "$plan_dir"' EXIT
terragrunt --log-disable init -reconfigure -no-color
terragrunt plan -out="$plan_dir/plan.out" -no-color
terragrunt --log-disable show -json "$plan_dir/plan.out" >"$plan_dir/plan.json"
conftest test --policy ../../../policy --output github "$plan_dir/plan.json"
terragrunt apply -no-color "$plan_dir/plan.out"
EOF
```

The AWS CLI `default` profile needs access to the shared S3/KMS state backend.
The kubeconfig must remain only on the trusted LAN machine. After Octelium is
healthy, rerun the normal protected `Terragrunt Apply` workflow to reconcile
the complete affected range. For an exact NOFX reconciliation, dispatch that
same workflow with `expected_sha` set to the current `main` SHA and
`argocd_app` set to `nofx`; this avoids applying unrelated shared SSM state.

The Octelium service catalog at `docs/examples/octelium/homelab-services.yaml`
defines:

- workload User `homelab-ci` with matching 30-day clientless-session and
  access-token lifetimes;
- Policy `homelab-ci-kubernetes-api-access`, which allows only the public
  clientless Kubernetes Service;
- public `KUBERNETES` Service `kubernetes-api-ci -> https://10.1.0.199:6443`.

On first installation, materialize the catalog's default upstream kubeconfig
Secret before applying the catalog. For later kubeconfig changes, use the
versioned staged-Secret cutover and rollback in `docs/octelium.md`; do not
overwrite the active Secret. Create or rotate the separate GitHub environment
credential after the Service catalog is healthy:

```sh
# First installation only; later rotations require a new --secret-name.
scripts/octelium-ci-kubeconfig-secret.sh --kubeconfig ~/.kube/config
octeliumctl apply docs/examples/octelium/homelab-services.yaml
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
When recovering through a temporary Octelium CLI session, pass the unique home
created by the recovery block below. If the public Octelium API path is not
carrying authenticated admin CLI calls reliably, point `--octelium-proxy` at a
local CONNECT proxy that forwards `octelium-api.stinkyboi.com:443` to the
in-cluster Istio gateway.

Avoid running raw `octeliumctl create cred` in shared terminals or CI logs
because it can print the generated token. If the helper cannot reach GitHub,
fix `gh auth status` or the target environment permissions, then rerun the
helper so the token is captured and stored without being displayed.

Rotate `OCTELIUM_CI_AUTH_TOKEN` every 21 days, on suspicious runs, after catalog
policy changes, and after runner image changes. Stage a new versioned Octelium
kubeconfig Secret and catalog cutover when the upstream Kubernetes credential
changes. If
CI receives Octelium `401` from authenticated `kubectl` against
`kubernetes-api-ci`, reapply the catalog and rotate the credential with
`scripts/octelium-ci-credential.sh`. Treat `403` as a policy or User-state
failure before rotating.
Recover the primary credential directly with the checked helper. Run this block
from the repository root; it uses a private, unique admin home and removes it
only after Octelium confirms logout:

```sh
(
  set -euo pipefail
  domain=stinkyboi.com
  octelium_tmp_root="${TMPDIR:-/tmp}"
  octelium_tmp_root="${octelium_tmp_root%/}"
  octelium_homedir="$(mktemp -d "${octelium_tmp_root}/octelium-admin.XXXXXX")"
  chmod 0700 "$octelium_homedir"

  # shellcheck disable=SC2329 # Invoked by the EXIT trap.
  close_admin_session() {
    exit_status=$?
    trap - EXIT
    if ! octeliumctl \
      --homedir "$octelium_homedir" \
      --domain "$domain" \
      --logout \
      get clusterconfig >/dev/null; then
      echo "error: server revocation failed; retained ${octelium_homedir} for retry" >&2
      exit 1
    fi
    rm -rf -- "$octelium_homedir"
    exit "$exit_status"
  }
  trap close_admin_session EXIT

  octeliumctl --homedir "$octelium_homedir" login --domain "$domain" --web
  scripts/octelium-ci-credential.sh --homedir "$octelium_homedir"
)
```

The helper applies the primary catalog with checked resource verification,
invalidates its stale Sessions, and writes the replacement token to both GitHub
environments. Dispatch and bind verification to the exact `main` commit:

```sh
set -euo pipefail
github_repo=Stuhlmuller/homelab
main_sha="$(gh api "repos/${github_repo}/commits/main" --jq .sha)"

latest_run_id() {
  gh run list \
    --repo "$github_repo" \
    --workflow "$1" \
    --event workflow_dispatch \
    --limit 1 \
    --json databaseId \
    --jq '.[0].databaseId // 0'
}

find_new_run_id() {
  local workflow="$1"
  local before_id="$2"
  local run_id
  for _ in {1..30}; do
    run_id="$(
      gh run list \
        --repo "$github_repo" \
        --workflow "$workflow" \
        --event workflow_dispatch \
        --limit 20 \
        --json databaseId \
        --jq "[.[] | select(.databaseId > ${before_id})] | max_by(.databaseId).databaseId // empty"
    )"
    if test -n "$run_id"; then
      printf '%s\n' "$run_id"
      return 0
    fi
    sleep 2
  done
  echo "error: no new ${workflow} run appeared" >&2
  return 1
}

wait_for_success() {
  local all_complete
  local run_id
  local state
  for _ in {1..360}; do
    all_complete=true
    for run_id in "$@"; do
      state="$(
        gh run view "$run_id" \
          --repo "$github_repo" \
          --json conclusion,status \
          --jq '.status + " " + (.conclusion // "")'
      )"
      case "$state" in
        "completed success") ;;
        "completed "*) echo "error: run ${run_id} ended ${state}" >&2; return 1 ;;
        *) all_complete=false ;;
      esac
    done
    test "$all_complete" = false || return 0
    sleep 30
  done
  echo "error: verification runs did not finish within three hours" >&2
  return 1
}

diagnostics_before_id="$(latest_run_id homelab-diagnostics.yml)"
apply_before_id="$(latest_run_id terragrunt-apply.yml)"
gh workflow run homelab-diagnostics.yml --repo "$github_repo" --ref main \
  -f expected_sha="$main_sha"
gh workflow run terragrunt-apply.yml --repo "$github_repo" --ref main \
  -f expected_sha="$main_sha"

diagnostics_run_id="$(find_new_run_id homelab-diagnostics.yml "$diagnostics_before_id")"
apply_run_id="$(find_new_run_id terragrunt-apply.yml "$apply_before_id")"
test "$(gh run view "$diagnostics_run_id" --repo "$github_repo" --json headSha --jq .headSha)" = "$main_sha"
test "$(gh run view "$apply_run_id" --repo "$github_repo" --json headSha --jq .headSha)" = "$main_sha"
wait_for_success "$diagnostics_run_id" "$apply_run_id"
```

Both exact-head runs must exit successfully. If either fails because the token
is unusable, rerun the same recovery block; no second short-lived recovery
identity is needed.

## Private Kubernetes Catalog Rollout

Use the focused workflow for changes to
`homelab-private-kubernetes-access` or `kubernetes-api.homelab`. From a clean
checkout at the current `main` commit and an authenticated Octelium
administrator session:

```sh
nix develop --command bash scripts/octelium-private-kubernetes-credential.sh rollout
```

The helper installs its cleanup trap before provisioning. It applies only the
dedicated WORKLOAD User plus the helper-only Credential template after replacing
its deliberately expired timestamp with a 30-minute expiry. It verifies the
complete live Credential spec, clears older Sessions, and rotates the token
directly into the `homelab-production` secret without printing it. It binds the
watch to the uniquely identified run it dispatched. The workflow extracts only
the reviewed Policy and Service, applies without `--prune`, then requires the
second identical apply to report no changes. On success, failure, or interrupt,
cleanup removes any unused Credential, clears and verifies Sessions, and deletes
and verifies the GitHub secret. For an emergency cleanup retry, run:

```sh
nix develop --command bash scripts/octelium-private-kubernetes-credential.sh revoke
```

This lane does not run Terragrunt or advance its successful full-apply
checkpoint. Roll back through a PR that restores the prior Policy or Service,
then provision and dispatch this workflow again.

## AWS Setup

The workflows use `AWS_ROLE_TO_ASSUME_HOMELAB` for both trusted PR plans and
protected post-merge applies. The operator unit owns the role trust and permits
only the protected plan and production environments in `homelab` and
`github-iac`:

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
            "repo:Stuhlmuller/github-iac:environment:github-iac-plan",
            "repo:Stuhlmuller/github-iac:environment:github-iac-production",
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

The role trust and additive IAM grant required to manage the chunked SSM reader
policies are declared in `IaC/operator/github-actions-role-policy`. The unit is
deliberately outside the GitHub workflow traversal: an automation role must not
be able to widen its own trust or replace the policy attached to itself.

For a trust-only change, use the targeted operator runbook in
`IaC/operator/README.md`. It conditionally imports only the existing role,
saves a plan for `aws_iam_role.github_actions`, rejects non-trust role drift and
any subject outside the four environments, applies those exact reviewed plan
bytes, and verifies live IAM. Do not run an un-targeted operator apply to roll
out only this trust change.

Full-unit policy, boundary, attachment, or user changes still use an
administrator-authenticated un-targeted plan after backend-free validation:

```sh
aws sso login --profile <administrator-profile>
cd IaC/operator/github-actions-role-policy
terragrunt --log-disable init -backend=false -lockfile=readonly -no-color
terragrunt --log-disable validate -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable init -reconfigure -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable state list
```

Before the first full-unit plan, import the existing GitHub Actions role and
External Secrets user when their state addresses are absent. Do not repeat an
import after its address is present:

```sh
AWS_PROFILE=<administrator-profile> terragrunt --log-disable import \
  'aws_iam_role.github_actions' Github-TF-State
AWS_PROFILE=<administrator-profile> terragrunt --log-disable import \
  'aws_iam_user.external_secrets' external-secrets_aws-ssm-auth
```

Then save, review, and apply the same plan from a private temporary directory:

```sh
umask 077
plan_dir="$(mktemp -d "${TMPDIR:-/tmp}/homelab-operator.XXXXXX")"
trap 'rm -rf -- "$plan_dir"' EXIT
AWS_PROFILE=<administrator-profile> terragrunt --log-disable plan -out="$plan_dir/plan.out" -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable show -no-color "$plan_dir/plan.out"
AWS_PROFILE=<administrator-profile> terragrunt --log-disable apply -no-color "$plan_dir/plan.out"
```

The resulting managed policy is limited to lifecycle operations on the ten
exact slots `homelab-ssm-parameter-reader-00` through `-09` and conditioned
attach/detach operations on the exact `homelab-ssm-parameter-readers` group;
attachment listing is read-only on that same group.

The unit also adopts the existing `external-secrets_aws-ssm-auth` IAM user,
removes direct managed and inline user policies, and attaches an operator-owned
permissions boundary. That boundary caps effective access at
`ssm:GetParameter`/`ssm:GetParameters` under `/homelab/*` plus decrypt/describe
access on the regional runtime-secret KMS key and denies every request made
with temporary STS credentials. The generated reader policies exclude the two
parameters that store this user's own access key. This keeps the existing group
management path from becoming an indirect route to unrelated AWS permissions
or a way for a compromised key to copy its replacement.

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
that phase only if the unapplied range did not change the AzureAD stack; a
range that changes the stack requires the credentials so identity drift is not
silently ignored.

## Local Equivalents

Run the same checks locally through the Nix shell:

```sh
nix develop --command pre-commit install
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

The PR plan script emits only generic progress messages. Inspect detailed plans
only in the trusted local session; do not paste them into GitHub.

Only run apply after the same validation has passed and the change has been
reviewed:

```sh
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/conftest-policies.sh
nix develop --command bash scripts/ci/terragrunt-apply.sh
```

Every full production apply compares against the latest successful historical
push apply or full dispatch SHA. Rerunning after one or more failed applies
therefore keeps the full unapplied range instead of considering only the newest
commit. Targeted Argo dispatches do not move that checkpoint.
