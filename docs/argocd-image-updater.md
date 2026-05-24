# Argo CD Image Updater

Argo CD Image Updater is installed as an Argo CD-managed Application from
`IaC/live/argocd-apps/argocd-image-updater`. It uses the upstream Helm chart
`argocd-image-updater` version `1.2.2` and runs in the `argocd` namespace.

The default policy is opt-in. The `homelab-annotation-opt-in` `ImageUpdater`
resource selects Applications in the `argocd` namespace only when they have:

- Label: `homelab.stuhlmuller.dev/image-updater=enabled`
- Annotations: `argocd-image-updater.argoproj.io/*` image configuration

The default write-back method is `argocd`, so this change does not commit Git
write credentials or create public webhooks. If a future app needs Git
write-back, add an ExternalSecret-backed credential contract first and document
the write-back target.

Example opt-in shape for a future Application:

```hcl
metadata = {
  annotations = {
    "argocd-image-updater.argoproj.io/image-list"          = "app=ghcr.io/example/app:1.x"
    "argocd-image-updater.argoproj.io/app.update-strategy" = "semver"
  }
  labels = {
    "homelab.stuhlmuller.dev/image-updater" = "enabled"
  }
}
```

Helm-backed Applications usually also need per-image annotations that identify
the chart values keys for the repository and tag. Keep those annotations beside
the Application registration so image automation remains reviewable.

Verification:

```sh
kubectl -n argocd get deploy argocd-image-updater-controller
kubectl -n argocd get imageupdater homelab-annotation-opt-in
kubectl -n argocd logs deploy/argocd-image-updater-controller
```
