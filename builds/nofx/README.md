# Maintained NOFX images

This recipe rebuilds the pinned NOFX release with passive, key-preserving model
configuration, validated backtest run IDs, and OKX US public historical candles
for new simulations. Historical decisions exclude current quant/ranking feeds
and use the simulated clock for position age. It does not enable live traders.
Deployment and operational
acceptance are documented in the [NOFX runbook](../../clusters/homelab/apps/nofx/README.md).

## Source and build contract

- [source.json](source.json) fixes upstream revision
  `bdfd8dc0d02c14b295eb36cbaee00d8402867927`, its archive SHA-256, and AGPL-3.0
  license identity.
- `prepare-source.py` verifies the download before extracting it, applies the
  ordered `patches/*.patch` files, and creates a temporary Docker context.
- Both Dockerfiles pin builder and upstream runtime images by digest. The
  backend reuses the release's TA-Lib runtime while replacing its executable;
  the frontend replaces the compiled web assets.
- OCI source labels identify this repository. The revision label records the
  homelab commit used for the build; both images retain the AGPL license label.

Use Bash, Git, Python 3.12 or newer, and a Linux-container Docker engine. The
Go and Node toolchains run inside the pinned builders. From the repository root:

```sh
bash builds/nofx/test.sh
bash builds/nofx/build.sh
```

Both scripts take no arguments, require no credentials, and clean their temporary
contexts. `test.sh` builds both Dockerfile `tests` targets against patched source.
`build.sh` builds the runtime images as `homelab-nofx-backend:build` and
`homelab-nofx-frontend:build`; it neither logs in nor pushes. Dependency downloads
require network access. The build targets also depend on the test stages.

## Corresponding source

The frontend footer links `/nofx-source.tar.gz`. That archive contains the full
patched upstream tree, license, dependency lock files, and this recipe with its
patches and pins. `homelab-build/revision.txt` records the original homelab build
revision so recipients can rebuild without a Git checkout:

```sh
tar -xzf nofx-source.tar.gz
bash homelab-build/test.sh
bash homelab-build/build.sh
```

Keep the download and upstream license notices when modifying these images.
After rollout, verify the footer download contains the patches and build recipe
matching the deployed image revision.

## Publish, update, and revert

The [NOFX Images workflow](../../.github/workflows/nofx-images.yml) tests and
builds PRs without publication credentials. Only a tested current `main` commit
can publish fixed GHCR repositories with tags `homelab-<full-main-sha>`; manual
dispatch requires the same exact SHA. The publish job rebuilds before logging
in and reports both digest references in its Actions summary.

First-time GHCR packages default to private. Explicit public publication and
anonymous image access must be verified before a separate reviewed deployment
PR pins the resulting digests. This recipe change alone does not deploy images.

For an upstream update, change the source revision and archive checksum together,
review the runtime/builder digest compatibility, rebase the patches, and require
both test and build commands to pass. Preserve historical-source provenance:
new UI runs select `okx_us`, while older saved runs without a source keep Binance.

To revert a build change, revert its recipe/patch commit through a PR and publish
the resulting new commit tag. To roll back deployment, stop simulations and
restore the previous reviewed image digests while retaining `nofx-data` and the
absolute executable/working-directory configuration. Returning to upstream
images restores their model-save side effects and Binance dependency.
