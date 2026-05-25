# Image Automation

Tags: #runbooks #argocd #image-updater

Source: `docs/argocd-image-updater.md`

Argo CD Image Updater is installed as an Argo CD-managed app from
`IaC/live/argocd-apps/argocd-image-updater`. It uses chart version `1.2.2` in
the `argocd` namespace.

## Policy

Image updates are opt-in only. An Application must carry:

- Label: `homelab.stuhlmuller.dev/image-updater=enabled`
- Image annotations under `argocd-image-updater.argoproj.io/*`

The default write-back method is `argocd`, not Git. Do not opt digest-pinned
workloads into the default write-back path because it can create runtime
parameter overrides outside git and replace reviewed `tag@sha256:digest`
values with tag-only values.

## Gate

No workloads currently opt in. Before enabling app automation, add a
Git-reviewed update path that preserves tag-and-digest pins.

Verify controller and selector:

```sh
kubectl -n argocd get deploy argocd-image-updater-controller
kubectl -n argocd get imageupdater homelab-annotation-opt-in
kubectl -n argocd logs deploy/argocd-image-updater-controller
```
