# Argo CD Image Updater Desired State

This path owns the cluster-local `ImageUpdater` selector policy for Argo CD
Image Updater. The Helm chart and controller configuration are rendered from
`values.yaml`; this Kustomize source adds the opt-in selector CR after the chart
installs its CRD.

Applications are not image-updated by default. To opt in, the Argo CD
Application must carry the `homelab.stuhlmuller.dev/image-updater=enabled`
label and the relevant `argocd-image-updater.argoproj.io/*` image annotations.
Keep the annotation values non-secret and document any Git write-back credential
change before enabling it.
