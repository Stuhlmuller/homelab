# Image Automation And Image Updater Retirement

Renovate is the repository's image-update path. Its built-in Helm values,
Kustomize, and Kubernetes managers open reviewed pull requests for image tags
and digests. `scripts/ci/static-checks.sh` rejects every repo-declared
container image that is not pinned as `tag@sha256:digest`.

OctoBot remains limited to `2.1.1` in `renovate.json` because `2.1.13` rejects
the retained PVC-backed `config.trading.paused` value. Other compatibility and
stateful migration decisions happen during normal pull-request review.

## Why Image Updater Was Retired

Argo CD Image Updater had been unable to push since May 2026 because its GitHub
App bot had no repository permission. Its stale Radarr selector also allowed
only `5.x` while desired state was already pinned to `6.3.0`, so a successful
reconcile could have proposed a downgrade. Renovate already covered the same
repository sources without a second controller or write credential.

## Safe Retirement Sequence

The retirement is safe if the Terragrunt apply is delayed or unavailable:

1. The existing live Application still reads
   `clusters/homelab/apps/argocd-image-updater/values.yaml` from `main`.
   Merging sets its controller Deployment to zero replicas.
2. The same Application auto-syncs the marker-only Kustomize source with prune
   enabled. That removes the `homelab-managed-images` custom resource and the
   `argocd-image-updater-git` ExternalSecret. The generated Secret is removed
   with its owning ExternalSecret.
3. The post-merge Terragrunt apply changes the Application to the marker-only
   source. Argo CD then prunes the remaining Helm resources. The removed
   `ImageUpdater` is sync wave `1`; the chart CRD is wave `0`. Argo CD prunes
   higher waves first and stops before lower waves if a prune fails, so the CR
   is gone before the CRD can be removed even if this apply wins the race with
   the first auto-sync.
4. The same Terragrunt workflow applies the SSM unit and removes the retired
   parameter paths from the External Secrets reader IAM policy. The parameters
   themselves remain state-managed tombstones.

Keep the inert Application, ConfigMap, zero-replica values file, and lock file
until Argo CD reports the marker revision synced and the retired controller
resources are absent. A later reviewed change may then remove the Terragrunt
unit and retirement directory.

The three `/homelab/argocd-image-updater/github-app/*` SSM parameters have no
runtime consumer or External Secrets reader IAM grant. They remain declared
only as OpenTofu state tombstones because the production policy rejects SSM
parameter deletion. Retire those values and state through a separate reviewed
secret-retirement workflow.

## Verification

Before the Terragrunt Application update has applied, expect zero desired
controller replicas and no active selector or credential consumer:

```sh
kubectl -n argocd get deploy argocd-image-updater-controller
kubectl -n argocd get imageupdater homelab-managed-images
kubectl -n argocd get externalsecret argocd-image-updater-git
```

After the Terragrunt apply and Argo CD sync:

```sh
argocd app get argocd-image-updater
kubectl -n argocd get configmap argocd-image-updater-retirement
kubectl -n argocd get deploy,serviceaccount,role,rolebinding \
  -l app.kubernetes.io/instance=argocd-image-updater
kubectl get clusterrole,clusterrolebinding \
  -l app.kubernetes.io/instance=argocd-image-updater
kubectl get crd imageupdaters.argocd-image-updater.argoproj.io
```

Expected result: the Application is `Synced` and `Healthy`, only the retirement
ConfigMap remains managed by it, and the retired controller resources are
absent. Do not delete the Terragrunt unit before this check passes.

## Rollback

Before the marker-only Application update, revert the retirement commit so the
existing Application restores its chart values and manifests. After that
update, revert and apply the restored Terragrunt unit so Argo CD owns the chart
again. Reintroducing the controller also requires a reviewed, working write
credential and corrected selectors; do not restore the broken contract merely
to preserve the old topology.
