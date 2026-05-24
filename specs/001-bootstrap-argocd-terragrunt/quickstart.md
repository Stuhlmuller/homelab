# Quickstart: Bootstrap Argo CD With Terragrunt

This quickstart describes the planned operator workflow. It is intentionally
written as the target runbook shape for implementation.

## Prerequisites

1. Work from a clean checkout of this repository on branch
   `001-bootstrap-argocd-terragrunt`.
2. Enter the project development shell so `terragrunt`, `tofu`, `kubectl`, and
   `helm` are available.
3. Confirm authenticated Kubernetes access to the homelab cluster.
4. Confirm external provider credentials are available without committing them.
5. Confirm no desired-state input depends on local environment variables.
6. Confirm the target revision
   `001-bootstrap-argocd-terragrunt` is available to Argo CD before expecting
   the self-management Application to sync from Git.

## Validate Before Apply

```sh
cd IaC
terragrunt hcl fmt --check
```

```sh
cd IaC/bootstrap/argocd
terragrunt init
terragrunt plan
```

Expected result:

- The plan creates or updates only the Argo CD bootstrap resources.
- No raw secret values appear in the plan output.
- The Argo CD install is ordered before the self-management Application.
- The Terragrunt source is the catalog `helm-release` module at `0.3.0`.
- The pinned chart is `argo-cd` version `9.5.15`.
- The Terragrunt `after_hook` applies the self-management Application after
  `applications.argoproj.io` is established.
- The Application source path is
  `clusters/homelab/argocd/self-management`.

## Apply Bootstrap

```sh
cd IaC/bootstrap/argocd
terragrunt apply
```

Expected result:

- Argo CD is installed in the `argocd` namespace.
- The Argo CD self-management Application exists.
- The Application points at this repository and the declared Argo CD
  desired-state path.

## Verify Handoff

```sh
kubectl get namespace argocd
kubectl -n argocd get applications.argoproj.io
kubectl -n argocd get pods
```

Expected result:

- The `argocd` namespace exists.
- Argo CD pods are running or progressing normally.
- The self-management Application is present.

For the first handoff, verify the self-management Application source path before
enabling automated prune and self-heal.

## Enable Steady-State Automation

After first-sync validation, update repository desired state to enable automated
sync with prune and self-heal for the self-management Application, then apply
the reviewed change through the documented workflow.

The concrete changes are:

- Add the active `syncPolicy.automated.prune` and
  `syncPolicy.automated.selfHeal` fields in
  `clusters/homelab/argocd/self-management/application.yaml`.

## Rollback

If the self-management Application is wrong but Argo CD is healthy:

1. Correct the repository source path, target revision, or sync settings.
2. Re-run `terragrunt plan`.
3. Re-run `terragrunt apply`.

If the Argo CD install itself is unhealthy:

1. Inspect the Helm release and Argo CD namespace with read-only `kubectl`
   commands.
2. Revert the repository change or apply the previous reviewed bootstrap state.
3. Record the failed state and validation output in the PR.

## Recovery Rules

- Missing CRDs: verify the Argo CD Helm install before retrying Application
  registration.
- Bad repo path: fix repository desired state; do not patch the live
  Application as a permanent fix.
- Missing credentials: inject credentials through the documented external or
  CI/CD path; do not commit them.
- Emergency live change: backfill the final desired state into this repository
  before the work is complete.
