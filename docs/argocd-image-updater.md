# Argo CD Image Updater

Argo CD Image Updater is installed as an Argo CD-managed Application from
`IaC/live/argocd-apps/argocd-image-updater`. It uses the upstream Helm chart
`argocd-image-updater` version `1.2.2` and runs in the `argocd` namespace.

The `homelab-managed-images` `ImageUpdater` resource in
`clusters/homelab/apps/argocd-image-updater/imageupdater.yaml` manages every
container image that this repository declares directly in workload Helm values
or raw manifests:

- `deluge`: BusyBox, Gluetun, and Deluge containers.
- `hummingbot`: bootstrap, app, and route status containers.
- `litellm`: LiteLLM database container.
- `media-postgres`: PostgreSQL StatefulSet image.
- `n8n`: n8n app container.
- `openclaw`: bootstrap, app, and proxy containers.
- `policy-bot`: Policy Bot Deployment image.
- `prowlarr`, `radarr`, and `sonarr`: PostgreSQL bootstrap and app containers.

Images owned only by upstream Helm chart defaults continue to move with chart
version updates. Add explicit values and an `ImageUpdater` `applicationRefs`
entry before treating a chart-default image as independently managed.

## Write-back

Image Updater uses Git write-back with GitHub pull-request mode. It does not
patch Argo CD Applications in place as the steady-state path. For each update it
pushes an `image-updater-*` branch and opens a pull request against `main`, so
the normal review, CI, and Argo CD reconciliation path still applies.

The write-back credential is the Kubernetes Secret
`argocd/argocd-image-updater-git`, created by the ExternalSecret at
`clusters/homelab/apps/argocd-image-updater/externalsecret.yaml`.

Required AWS SSM Parameter Store values:

| Parameter | Secret key | Purpose |
| --- | --- | --- |
| `/homelab/argocd-image-updater/github-app/id` | `githubAppID` | GitHub App ID |
| `/homelab/argocd-image-updater/github-app/installation-id` | `githubAppInstallationID` | GitHub App installation ID for this repository or owner |
| `/homelab/argocd-image-updater/github-app/private-key` | `githubAppPrivateKey` | GitHub App private key |

The GitHub App must be installed on `Stuhlmuller/homelab` with repository
contents write access and pull-request write access. Store the private key as a
SecureString outside git.

## Update policy

The global policy uses semantic-version updates and ignores `latest`, `main`,
and `dev` tags. Images whose upstream tags are not plain semver use
per-image `newest-build` rules with regular-expression allow lists.

Image Updater writes to the source paths that Argo CD already renders:

- Helm values files use `helmvalues:/clusters/homelab/apps/<app>/values.yaml`.
- Raw-manifest apps use `kustomization:/clusters/homelab/apps/<app>`.

Because these paths are explicitly managed by Image Updater and reviewed through
pull requests, `scripts/ci/static-checks.sh` allows tag-only image fields inside
those write-back targets. Unmanaged image fields still must be pinned as
`tag@sha256:digest`.

## Verification

```sh
kubectl -n argocd get deploy argocd-image-updater-controller
kubectl -n argocd get externalsecret argocd-image-updater-git
kubectl -n argocd get secret argocd-image-updater-git
kubectl -n argocd get imageupdater homelab-managed-images
kubectl -n argocd logs deploy/argocd-image-updater-controller
```

Expected result:

- The controller Deployment is available.
- `argocd-image-updater-git` is synced from AWS SSM and contains the GitHub App
  credential keys.
- `homelab-managed-images` reports reconciliation status for the managed
  Applications.
- New image versions create GitHub pull requests rather than live-only Argo CD
  parameter overrides.
