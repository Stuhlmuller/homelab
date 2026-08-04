# Argo CD Image Updater Desired State

This path owns the cluster-local Image Updater policy for Argo CD Image
Updater. The Helm chart and controller configuration are rendered from
`values.yaml`; this Kustomize source adds the GitHub App credential
`ExternalSecret` and the `homelab-managed-images` selector CR after the chart
installs its CRD.

`homelab-managed-images` manages the images listed in `imageupdater.yaml`. It
writes updates back to GitHub pull requests with the
`argocd-image-updater-git` Secret instead of storing live-only Argo CD
parameter overrides. `renovate.json` disables overlapping Docker updates for
those write-back targets. BusyBox remains Renovate-owned because Deluge uses it
in both Helm values and raw manifests; OctoBot remains review-pinned while its
PVC migration is blocked.

`argocd-image-updater-git` uses `refreshPolicy: OnChange`. After replacing the
GitHub App credential values in AWS SSM, bump
`homelab.rst.io/github-app-credentials-ssm-version` on the ExternalSecret so
External Secrets refreshes the in-cluster Secret without hand-editing it.

Add a new workload image to `imageupdater.yaml` in the same PR that introduces
the image and add its write-back path to the Renovate exclusion in the same PR.
Otherwise keep the image pinned as `tag@sha256:digest`.
