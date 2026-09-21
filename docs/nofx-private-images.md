# Private NOFX images

Keep both Harbor `homelab/homelab-nofx-*` repositories and their retained
`ghcr.io/stuhlmuller/homelab-nofx-*` originals private. Anonymous HTTP 401 is
expected. The NOFX application login and registry authentication are separate:
the kubelet needs a registry credential before it can start either container.

The initial maintained rollout used revision
`f76c27834ff987aa1dfad81d0c9ff273be7dd3cd`, migrated to Harbor without changing
its digests. The successful
[migration workflow](https://github.com/Stuhlmuller/homelab/actions/runs/35486238550)
verified complete read-only pulls and denied anonymous access. Keep those
artifacts as recovery history; subsequent builds publish directly to Harbor.
[deployment.yaml](../clusters/homelab/apps/nofx/deployment.yaml) is the source of
truth for the desired backend and frontend references.

Both deployments use `imagePullSecrets: [{name: harbor-pull}]`, rendered by the
existing ExternalSecret from `/homelab/nofx/harbor-pull-password`. The read-only
robot credential never enters NOFX containers. See the
[migration contract](../builds/nofx/README.md#existing-ghcr-package-migration).
Retain the GHCR originals and credential as a reviewed recovery path.

## GHCR recovery credential contract

Use a dedicated GitHub classic personal access token belonging to
`rstuhlmuller`, with only `read:packages` and a chosen expiry. The account must
have read access to both packages; authorize organization SSO if required.
GitHub documents this credential type for
[private Container Registry pulls](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-with-a-personal-access-token-classic).
Do not copy the broad GitHub CLI credential or a workflow's temporary
`GITHUB_TOKEN` into the cluster.

The GitHub Terraform provider cannot issue a personal access token. Its
[`github_app_token` data source](https://registry.terraform.io/providers/integrations/github/latest/docs/data-sources/app_token)
requires an already registered App, installation, and private key. Generating a
random string in OpenTofu would not create a GitHub credential. Token issuance
therefore remains an authenticated operator prerequisite; the homelab owns its
storage and deployment declaratively.

The data path is:

1. Protected `homelab-production` environment secret `NOFX_GHCR_READ_TOKEN`.
2. The reviewed `NOFX Registry Credential` workflow validates the account,
   scopes, and authenticated pulls of both fixed image digests.
3. It updates the existing SSM SecureString
   `/homelab/nofx/ghcr-read-token` in `us-west-2`, encrypted with `alias/aws/ssm`.
4. External Secrets refreshes `nofx/nofx-registry-auth` every five minutes.
   The target type is `kubernetes.io/dockerconfigjson`, scoped to `ghcr.io`.
5. A reviewed GHCR rollback attaches this Secret through `imagePullSecrets`
   together with both GHCR image references. NOFX containers receive neither
   a token environment variable nor a token volume mount.

The SSM parameter and exact reader permissions belong to
`IaC/.catalog/units/live/aws-ssm-parameters/terragrunt.hcl`. The registry
ExternalSecret belongs to `clusters/homelab/apps/nofx`. Parameter creation uses
the existing OpenTofu placeholder contract; the credential workflow cannot
create a missing slot or write another parameter.

## GHCR bootstrap without interrupting NOFX

The first stage, [PR #1031](https://github.com/Stuhlmuller/homelab/pull/1031),
merged at `0b352ebd05a944de46b0cdda7240edbc10671d76`. It retains the original
upstream images and does not attach the new pull Secret. A placeholder credential is not
an authenticated image pull and must never be treated as rollout readiness.
The new ExternalSecret uses sync wave `-1`; until the SSM slot exists, Argo CD
may show a pending sync or unhealthy ExternalSecret. Existing pods keep running.
Provision the slot through the reviewed infrastructure apply to resolve this
expected bootstrap state.

Run the documented protected Terragrunt apply for that exact reviewed `main`
commit to create the parameter and update the External Secrets reader policy.
Review its plan before approval. Require Argo CD to reconcile the new
ExternalSecret through GitOps; do not patch Secrets or Deployments manually.

Create the dedicated classic PAT in GitHub's authenticated UI. Store it with the
CLI's interactive secret input so it is absent from shell history and command
arguments:

```sh
gh secret set NOFX_GHCR_READ_TOKEN \
  --repo Stuhlmuller/homelab --env homelab-production
```

Then dispatch the reviewed workflow using the actual current `main` SHA:

```sh
reviewed_sha="$(gh api repos/Stuhlmuller/homelab/git/ref/heads/main --jq .object.sha)"
gh workflow run nofx-registry-credential.yml \
  --repo Stuhlmuller/homelab --ref main -f expected_sha="$reviewed_sha"
gh run list --repo Stuhlmuller/homelab \
  --workflow nofx-registry-credential.yml --limit 1
```

Approve the protected environment only after reviewing the exact commit and
successful static/policy checks. The script requires both full image pulls to
succeed before writing the credential. It emits validation status without
tokens, authorization headers, registry configuration, or decrypted parameters.
The final AWS CLI write reads a mode `0600` JSON file inside a mode `0700`
temporary directory. The helper removes both on success or failure; they never
enter the checkout or uploaded artifacts. This uses AWS CLI's documented
[input-file mechanism](https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-skeleton.html).
Do not substitute `/dev/stdin`: the reproduced CLI input parsing failure occurs
before AWS receives the write.

Before any GHCR rollback, require credential workflow success, ExternalSecret
`Ready=True`, and `status.refreshTime` later than credential injection. `Ready`
alone can describe the old placeholder; its transition timestamp need not change
when a healthy Secret refreshes. A failed credential run leaves the rollout gate
closed even when static checks pass.

## Harbor runtime acceptance

The US connection and dashboard rollout targets source revision
`689df14c755c43dfdfc744316f7a526081d7a2c6`, merged in
[PR #1066](https://github.com/Stuhlmuller/homelab/pull/1066).
[NOFX Images run 35558011393](https://github.com/Stuhlmuller/homelab/actions/runs/35558011393)
passed publication and private pull verification. Both manifest references
come from its verified digest report.
Patch `0011` routes signed REST calls through `us.okx.com` for the confirmed US
account and distinguishes unavailable owned traders from missing/foreign IDs.
It preserves database-only equity history and shows safe dashboard guidance.
This changes no credential and adds neither spot execution nor independent
agent returns. Live authentication still requires read-only runtime
verification.

The prior startup-error build `9716e9d9121a062029c72dc5f03f0d266a166650` from
[run 35555807176](https://github.com/Stuhlmuller/homelab/actions/runs/35555807176)
passed publication and private pull verification. Retain it as recovery history.
Its patch `0010` rejects failed account-config reads even with a saved balance
and displays known `50119` guidance, but still uses the global OKX host.

The previous shared-account rollout used source
`05fcf60be529c063ae9f5fa16494466c3db0f400`, merged in
[PR #1054](https://github.com/Stuhlmuller/homelab/pull/1054).
[NOFX Images run 35551197231](https://github.com/Stuhlmuller/homelab/actions/runs/35551197231)
passed publication and private pull verification. That source preserves parsed
leverage caps and hidden trader creation, and stops OKX openings when leverage
verification or updates fail.
[deployment.yaml](../clusters/homelab/apps/nofx/deployment.yaml) owns desired
image references; publication alone establishes neither deployment nor returns.
The earlier `25bceceb` competition build was deployed by
[PR #1052](https://github.com/Stuhlmuller/homelab/pull/1052); retain that evidence
as history, not acceptance of these additional fixes.

Before merging the image-pin PR:

1. Require successful private Harbor publication of that exact build revision.
   Copy both verified digest references from the publication report into
   [deployment.yaml](../clusters/homelab/apps/nofx/deployment.yaml); never infer
   a digest from a tag or reuse the old migration result as new-build evidence.
   For builds with a successful `Report Published NOFX Digests` job, download
   the fixed `nofx-published-images-<source-sha>` artifact with `gh run download`
   and read its `nofx-published-images.txt`. Earlier builds expose these
   references only in the Actions summary, which the `gh` API does not return.
2. Verify `nofx/harbor-pull` ExternalSecret `Ready=True`. The earlier migration
   proves the read-only robot contract; readiness alone does not prove a new
   image can be pulled.
3. Verify every live trader is stopped using a fresh authenticated UI check or
   the read-only database check below. Earlier screenshots do not satisfy this
   gate: running traders auto-resume when the backend restarts.
4. Finish or stop simulations before rollout. Cold resume does not restore the
   saved strategy object reliably; start a fresh matched round after restart.

With existing Kubernetes operator access, these queries return only counts,
without reading credentials, balances, or trade history. Require both counts
to be zero and the lock-file lookup to succeed with no results immediately
before merging the rollout. A command failure is not evidence of inactivity.

```sh
kubectl --request-timeout=10s -n nofx exec deployment/nofx-backend -- \
  sqlite3 -readonly /app/data/data.db \
  'SELECT COUNT(*) FROM traders WHERE COALESCE(is_running, 1) <> 0;'
kubectl --request-timeout=10s -n nofx exec deployment/nofx-backend -- \
  sqlite3 -readonly /app/data/data.db \
  "SELECT COUNT(*) FROM backtest_runs WHERE state IN ('running', 'paused');"
kubectl --request-timeout=10s -n nofx exec deployment/nofx-backend -- \
  find /app/data/backtests -type f -name lock -print
```

The pinned manager can persist `created` while a first decision is already
running, so the database simulation count alone is insufficient. Active runners
hold a heartbeat lock from construction through terminal cleanup. Investigate
any lock or unexplained state through read-only runtime/UI inspection; do not
delete locks to pass this check. Preserve known failed-start records.

These commands do not stop traders, change application state, or provide an
authenticated UI session. Use the UI for model configuration and new simulations.

After GitOps rollout, require Argo CD `Synced` and `Healthy`, both containers
ready at the declared Harbor digests, and the source download matching the build
revision. Then perform the functional checks in the
[NOFX README](../clusters/homelab/apps/nofx/README.md): verify patches `0007`–`0011`
in the source download and confirm all traders remain stopped and the three
shared-account drafts remain hidden after restart. Reload the authenticated UI
only after a fresh persisted stopped-state check, because runtime loading can
auto-start saved running traders. Select **AI Traders → View** and inspect its
read-only account/positions requests. Require HTTP 200 from successful exchange
reads; a safe `503 TRADER_UNAVAILABLE` verifies
error handling but leaves authentication unresolved. Missing/foreign IDs must
remain 404. Recheck all traders stopped afterward. Do not press Start or replace
failed reads with empty successes.
Reproduce parser, visibility-migration, startup, signed US transport, dashboard
ownership, public-history, and Axios regressions through the image test target.
These checks use mocks and place no live orders. Successful authentication does
not add US spot support, product eligibility, or independent agent returns.
For a fresh
[simulation comparison](nofx-agent-competition.md), all expected decisions
must pass before scoring; publication and Pod readiness do not establish a valid
competition result. Live activation remains a user action.

## Recovery token rotation and failure modes

Before expiry, create a replacement dedicated token, update the same protected
environment secret, and dispatch the workflow at current reviewed `main`.
Retain the old token until the new workflow succeeds and External Secrets has
refreshed. Revoke the old token through GitHub's normal operator flow afterward.
Do not use token rotation to grant repository or package-write permissions.

An invalid token, unexpected owner or scopes, failed image pull, or missing SSM
slot prevents any credential write. Investigate the failed check; do not make
the packages public. A successful image publication job proves that CI can push
images, not that Kubernetes can pull them.

Credential workflow logs identify fixed stages such as `backend-pull` and
`ssm-write`, with allowlisted error categories. Command output stays private.
For a registry authorization failure, check package read access and organization
SSO authorization; for an SSM error, check the declared slot and workflow role.
An unknown error remains redacted. Do not enable shell tracing or print Docker
configuration, command responses, or parameter values to diagnose it.

If startup or functional acceptance fails, restore the prior reviewed Harbor
backend/frontend pair through a PR, retaining `harbor-pull`, the PVC, and the
working-directory configuration. The prior `9716e9d9` pair retains the startup
error guidance but restores global-host routing and the old dashboard lookup.
The initial `f76c278` pair is recorded in
[PR #1036](https://github.com/Stuhlmuller/homelab/pull/1036); restoring it also
restores its structured-output and leverage limitations. A GHCR recovery must
switch both references and their pull Secret together using the gates above.
Retain credentials and application data during diagnosis; start fresh simulation
runs after rollback rather than cold-resuming a round.
