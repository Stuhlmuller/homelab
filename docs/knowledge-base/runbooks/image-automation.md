# Image Automation

Tags: #runbooks #argocd #image-updater

Source: `docs/argocd-image-updater.md`

Argo CD Image Updater is installed as an Argo CD-managed app from
`IaC/live/argocd-apps/argocd-image-updater`. It uses chart version `1.2.2` in
the `argocd` namespace.

## Policy

`clusters/homelab/apps/argocd-image-updater/imageupdater.yaml` owns the
`homelab-managed-images` `ImageUpdater` resource. It manages every image this
repo declares directly in workload Helm values or raw manifests:

- Deluge, Dispatcharr, LiteLLM, Media Postgres, n8n-postgres, n8n, OctoBot,
  OpenClaw, Policy Bot, Prowlarr, Radarr, and Sonarr.
- Chart-default images remain tied to chart version updates until the repo adds
  explicit values plus an `ImageUpdater` entry for them.
- OctoBot is temporarily allow-listed to `2.1.1`; `2.1.13` rejected the current
  PVC-backed `config.trading.paused` field during startup migration.

Image Updater uses Git write-back with GitHub pull-request mode, not live-only
Argo CD parameter overrides. The write-back credential is the
`argocd-image-updater-git` ExternalSecret in the `argocd` namespace.

## Secret Contract

Required AWS SSM parameters:

- `/homelab/argocd-image-updater/github-app/id`
- `/homelab/argocd-image-updater/github-app/installation-id`
- `/homelab/argocd-image-updater/github-app/private-key`

The GitHub App needs repository contents write access and pull-request write
access for `Stuhlmuller/homelab`. The ExternalSecret uses `OnChange`; bump
`homelab.rst.io/github-app-credentials-ssm-version` after credential
replacement so External Secrets refreshes the Kubernetes Secret.

## Gate

`scripts/ci/static-checks.sh` still requires unmanaged image fields to be pinned
as `tag@sha256:digest`. Tag-only image fields are allowed only inside
ImageUpdater write-back targets listed in `homelab-managed-images`.

Verify controller, credential, and selector:

```sh
kubectl -n argocd get deploy argocd-image-updater-controller
kubectl -n argocd get externalsecret argocd-image-updater-git
kubectl -n argocd get imageupdater homelab-managed-images
kubectl -n argocd logs deploy/argocd-image-updater-controller
```

## Related Notes

- [[../architecture/gitops-flow]]
- [[../architecture/secrets-and-identity]]
- [[../workloads/inventory]]
