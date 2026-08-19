# Multica Break-Glass Recovery

Use this only when the normal Octelium clientless Kubernetes CI credential is
broken and Multica must be recovered before the standard Terragrunt Apply path
can run.

## Prerequisites

- PR containing `.github/workflows/break-glass-multica-recovery.yml` is merged
  to `main`.
- `homelab-production` environment approval is available for the dispatch.
- `KUBE_CONFIG_B64` is present and grants temporary production Kubernetes
  access.
- `AWS_ROLE_TO_ASSUME_HOMELAB` is present as a repository variable or secret.
- The expected target is only the SSM parameter unit and the Multica Argo CD
  Application unit.

## Dispatch

From the GitHub UI, run **Break Glass Multica Recovery** on `main` and approve
`homelab-production` when prompted.

From the CLI, if authenticated:

```sh
gh workflow run break-glass-multica-recovery.yml --ref main
```

## Expected Output

The workflow must:

1. verify Kubernetes access with `kubectl --request-timeout=15s version`;
2. run `terragrunt stack generate`;
3. adopt existing GitHub runner and Cordium SSM parameters into state when they
   already exist in AWS;
4. plan the SSM parameter unit, render `plan.json`, run Conftest, and apply the
   saved plan;
5. plan the Multica Application unit, render `plan.json`, run Conftest, and
   apply the saved plan;
6. poll `application/multica` until Argo CD reports `Synced` and `Healthy`.

A successful run ends by printing `kubectl -n argocd get application multica -o
wide` output. A run that cannot reach `Synced` and `Healthy` within the bounded
polling window must fail.

## Failure Handling

If the SSM unit fails before apply, inspect the generated plan and state list for
`IaC/live/aws-ssm-parameters`. Import any pre-existing SSM parameter through the
state owner before retrying; do not create or overwrite parameters manually.

If the Multica unit fails before apply, inspect the saved plan and Conftest
output. Fix the repository source, open a PR, and retry only after the recovery
workflow on `main` includes the fix.

If the workflow applies one unit and later fails, reconcile through Terragrunt:

```sh
cd IaC
terragrunt stack generate
cd live/aws-ssm-parameters
terragrunt init -no-color
terragrunt state list
terragrunt plan -out plan.out -no-color
terragrunt --log-disable show -json plan.out >plan.json
conftest test --policy ../../../policy --output github plan.json
```

Then repeat the same saved-plan policy gate in `IaC/live/argocd-apps/multica`.
Do not patch or annotate the live Argo CD Application by hand to force recovery.

## Rollback And Retirement

Rollback should be a normal repository change that updates or removes the
Multica Application source, not a live cluster mutation. After the Octelium CI
credential is repaired with `scripts/octelium-ci-credential.sh`, remove this
workflow in a follow-up PR and return to the standard Terragrunt Apply path.
