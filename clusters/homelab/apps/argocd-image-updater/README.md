# Argo CD Image Updater Retirement

This is an inert pruning target. `retirement-marker.yaml` keeps the Argo CD
source non-empty while it removes the retired selector and ExternalSecret.
`values.yaml` scales the controller to zero for live Applications that still
reference the former Helm source before Terragrunt updates their source list.

Keep this directory until the marker-only Application is synced and all retired
chart resources are absent. See `docs/argocd-image-updater.md` for verification
and final removal gates. Renovate owns repository image updates.
