# Argo CD Image Updater

Argo CD Image Updater is installed as an Argo CD-managed Application from
`IaC/live/argocd-apps/argocd-image-updater`. It uses the upstream Helm chart
`argocd-image-updater` version `1.2.2` and runs in the `argocd` namespace.

The `homelab-managed-images` `ImageUpdater` resource in
`clusters/homelab/apps/argocd-image-updater/imageupdater.yaml` manages these
repository-declared images:

- `affine`: AFFiNE server/migration init container, pgvector PostgreSQL, and
  Redis images; updates remain within AFFiNE `0.27`, pgvector `0.8` on
  PostgreSQL 16, and Redis `8.2` until their stateful upgrade paths are
  reviewed.
- `deluge`: Gluetun and all Deluge containers. BusyBox stays Renovate-owned so
  its Helm-values and raw-manifest uses move together.
- `dispatcharr`: Dispatcharr web and Celery containers plus the Redis sidecar.
  The dedicated PostgreSQL manifest remains review-pinned because this
  multi-source Application uses its Image Updater write-back target for Helm
  values.
- `litellm`: LiteLLM database container.
- `media-postgres`: PostgreSQL StatefulSet image.
- `n8n-postgres`: n8n PostgreSQL StatefulSet image.
- `n8n`: n8n app container.
- `openclaw`: bootstrap, app, and proxy containers.
- `policy-bot`: Policy Bot Deployment image.
- `prowlarr`, `radarr`, and `sonarr`: PostgreSQL bootstrap and app containers.

OctoBot remains manually review-pinned to `2.1.1` because `2.1.13` rejected
the existing PVC-backed `config.trading.paused` field during startup migration.

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
The ExternalSecret uses `refreshPolicy: OnChange`. After replacing GitHub App
values in SSM, bump the
`homelab.rst.io/github-app-credentials-ssm-version` annotation so External
Secrets reconciles the in-cluster Secret without direct edits.

Required AWS SSM Parameter Store values:

| Parameter | Secret key | Purpose |
| --- | --- | --- |
| `/homelab/argocd-image-updater/github-app/id` | `githubAppID` | GitHub App ID |
| `/homelab/argocd-image-updater/github-app/installation-id` | `githubAppInstallationID` | GitHub App installation ID for this repository or owner |
| `/homelab/argocd-image-updater/github-app/private-key` | `githubAppPrivateKey` | GitHub App private key |

The GitHub App must be installed on `Stuhlmuller/homelab` with repository
contents write access and pull-request write access. Store the private key as a
SecureString outside git.

After increasing either permission, the installation owner must approve the
pending permission update before new installation tokens receive it. Permission
changes alone do not require replacing the App ID, installation ID, or private
key in SSM.

## Update policy

The global policy uses semantic-version updates and ignores `latest`, `main`,
and `dev` tags. Flavor-suffixed semantic tags use `-0` constraints plus regular
expression allow lists; this preserves semantic version ordering while
admitting the required suffix. `newest-build` is reserved for non-semver tags
such as commit hashes and LiteLLM's prefixed stable tags.

n8n is the exception: Image Updater follows the official GHCR `stable` tag by
digest. n8n prereleases use ordinary semantic versions, and `docker.n8n.io` is
backed by Docker Hub's anonymous pull limits, so semver selection can choose a
prerelease while repeated manifest lookups can be rate-limited.

Image Updater writes to the source paths that Argo CD already renders:

- Helm values files use `helmvalues:/clusters/homelab/apps/<app>/values.yaml`.
- Raw-manifest apps use `kustomization:/clusters/homelab/apps/<app>`.

Because these paths are explicitly managed by Image Updater and reviewed through
pull requests, `scripts/ci/static-checks.sh` allows tag-only image fields inside
those write-back targets. `renovate.json` disables overlapping Docker updates in
those targets. BusyBox is the deliberate exception and remains Renovate-owned
across its Helm-values and raw-manifest uses. Unmanaged image fields still must
be pinned as `tag@sha256:digest`.

## Verification

```sh
kubectl -n argocd get deploy argocd-image-updater-controller
kubectl -n argocd get externalsecret argocd-image-updater-git
kubectl -n argocd get secret argocd-image-updater-git
kubectl -n argocd get imageupdater homelab-managed-images
kubectl -n argocd logs deploy/argocd-image-updater-controller
gh api 'repos/Stuhlmuller/homelab/collaborators/stuhlmuller-homelab-argocd%5Bbot%5D/permission' --jq .permission
```

Expected result:

- The controller Deployment is available.
- `argocd-image-updater-git` is synced from AWS SSM and contains the GitHub App
  credential keys.
- The GitHub App bot reports `write`, `maintain`, or `admin` repository access.
- `homelab-managed-images` reports reconciliation status for the managed
  Applications without an `Error=True` condition.
- New image versions create GitHub pull requests rather than live-only Argo CD
  parameter overrides.
