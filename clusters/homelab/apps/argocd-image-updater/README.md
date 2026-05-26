# Argo CD Image Updater Desired State

This path owns the cluster-local Image Updater policy for Argo CD Image
Updater. The Helm chart and controller configuration are rendered from
`values.yaml`; this Kustomize source adds the GitHub App credential
`ExternalSecret` and the `homelab-managed-images` selector CR after the chart
installs its CRD.

`homelab-managed-images` manages every container image that this repository
declares directly in workload Helm values or raw manifests. It writes updates
back to GitHub pull requests with the `argocd-image-updater-git` Secret instead
of storing live-only Argo CD parameter overrides.

`argocd-image-updater-git` uses `refreshPolicy: OnChange`. After replacing the
GitHub App credential values in AWS SSM, bump
`homelab.rst.io/github-app-credentials-ssm-version` on the ExternalSecret so
External Secrets refreshes the in-cluster Secret without hand-editing it.

Add a new workload image to `imageupdater.yaml` in the same PR that introduces
the image, or keep the image pinned as `tag@sha256:digest` until it has an
explicit Image Updater write-back target.
