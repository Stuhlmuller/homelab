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

The next rollout targets competition build
`25bcecebfd6d18f4a2b41f9bbd7640ad742f9e1b` from
[NOFX Images run 35494703264](https://github.com/Stuhlmuller/homelab/actions/runs/35494703264),
which successfully published and verified both private Harbor images. It adds
strict historical OpenRouter decisions, an execution-time leverage cap, and a
factual selected-run comparison table. Runtime acceptance remains separate;
successful publication does not establish deployment or competition results.

Before merging the image-pin PR:

1. Require successful private Harbor publication of that exact source revision.
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
[NOFX README](../clusters/homelab/apps/nofx/README.md), including a fresh
[simulation comparison](nofx-agent-competition.md). Image publication and Pod
readiness do not establish a valid competition result.

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
working-directory configuration. The initial `f76c278` pair is recorded in
[PR #1036](https://github.com/Stuhlmuller/homelab/pull/1036); restoring it also
restores its structured-output and leverage limitations. A GHCR recovery must
switch both references and their pull Secret together using the gates above.
Retain credentials and application data during diagnosis; start fresh simulation
runs after rollback rather than cold-resuming a round.
