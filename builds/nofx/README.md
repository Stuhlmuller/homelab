# Maintained NOFX images

This recipe rebuilds the pinned NOFX release with passive, key-preserving model
configuration, validated backtest run IDs, and OKX US public historical candles
for new simulations. Historical decisions exclude current quant/ranking feeds
and use the simulated clock for position age. OKX construction reads account
mode without trying to change it. It does not enable live traders. Deployment
and operational acceptance are documented in the
[NOFX runbook](../../clusters/homelab/apps/nofx/README.md).

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
builds PRs without publication credentials. A tested current `main` commit can
publish these private Harbor repositories after the `homelab-production`
environment gate:

- `harbor.stinkyboi.com/homelab/homelab-nofx-backend`
- `harbor.stinkyboi.com/homelab/homelab-nofx-frontend`

Tags are `homelab-<full-main-sha>`; manual dispatch requires the exact current
`main` SHA. The publish job rebuilds before AWS authentication or registry
login. It reads `/homelab/harbor/robot-push-password` from SSM in `us-west-2`
for the `robot$homelab+publisher` account. Credentials stay in restrictive
temporary files and the public Actions summary contains only verified digest
references. Transfers and transport diagnostics remain private.

The CI helper uses the existing Octelium Kubernetes CI lane to port-forward
Istio HTTPS on the ephemeral runner. A temporary `/etc/hosts` entry preserves
`harbor.stinkyboi.com` certificate validation while uploads bypass the public
Cloudflare HTTP request-size limit. Cleanup removes the forwarding process,
host entry, kubeconfig, registry credentials, and private logs. Harbor, its TLS
certificate, project/robot reconciliation, and production CI access must be
ready before publication.

### Existing GHCR package migration

The [migration inventory](../../scripts/config/harbor-migration.json) records
four private artifacts: backend and frontend releases published by
[run 34815485548](https://github.com/Stuhlmuller/homelab/actions/runs/34815485548)
at revision `f76c27834ff987aa1dfad81d0c9ff273be7dd3cd` and
[run 34926391605](https://github.com/Stuhlmuller/homelab/actions/runs/34926391605)
at revision `0b352ebd05a944de46b0cdda7240edbc10671d76`. Authenticated GHCR and
GitHub Packages inventory on 2026-09-19 confirmed two active tagged versions
per repository and no untagged versions.
After Harbor is ready, dispatch the
[migration workflow](../../.github/workflows/harbor-migrate.yml) from current
`main` with that checkout's exact SHA as `expected_sha`. The inventory's source
revisions stay fixed to the original builds; the dispatch SHA identifies the
reviewed migration code.

The workflow requires static checks and the production environment gate,
reads private GHCR packages using its repository-scoped `GITHUB_TOKEN`, and
copies the fixed digests with `skopeo copy --all --preserve-digests`. It verifies
the SHA-256 of each destination's raw manifest against the recorded source
digest. It then reads `/homelab/nofx/harbor-pull-password` into a separate
temporary authfile for `robot$homelab+pull`, downloads all four complete
artifacts to separate fresh directories, and verifies those manifest digests.
Anonymous requests
must receive an authentication denial with an explicitly empty authfile and
`--no-creds`; network failures do not count as denial. Only then does it publish
the result. Downloaded blobs and all credentials are removed on success or
failure. Original tags and GHCR sources remain; reruns copy the same content.
Future builds publish directly to Harbor.

Live inspection on 2026-09-19 confirmed NOFX still runs upstream images; there
are no deployed consumers of these custom packages. Registry-origin cutover
applies only to an existing custom-image consumer and must preserve its exact
deployed digest. Adopting the maintained NOFX release is a separate functional
rollout, with the acceptance checks in the linked runbook. The successful
[migration](https://github.com/Stuhlmuller/homelab/actions/runs/35486238550)
preserved all historical digests and verified complete read-only pulls. The
maintained runtime selects the migrated
`f76c27834ff987aa1dfad81d0c9ff273be7dd3cd` images from Harbor with the
namespace-scoped `harbor-pull` Secret. Require ready Pods at both exact digests
before declaring Kubernetes pull acceptance. Keep Harbor repositories private.
For a registry rollback,
retain the artifacts until consumers have switched to another verified private
registry through reviewed desired state.

The retained GHCR packages remain private. Their recovery pull credential is
covered by the [private-image runbook](../../docs/nofx-private-images.md).
Do not change package visibility to work around a missing pull credential.

For an upstream update, change the source revision and archive checksum together,
review the runtime/builder digest compatibility, rebase the patches, and require
both test and build commands to pass. Preserve historical-source provenance:
new UI runs select `okx_us`, while older saved runs without a source keep Binance.

To revert a build change, revert its recipe/patch commit through a PR and publish
the resulting new commit tag. To roll back deployment, stop simulations and
restore the previous reviewed image digests while retaining `nofx-data` and the
absolute executable/working-directory configuration. Returning to upstream
images restores their model-save side effects and Binance dependency.

## Private image signing

New publications run the repository-owned
[signing Job](../../clusters/homelab/apps/harbor/signing-job.yaml) inside the
homelab. cert-manager generates a dedicated P-256 key in `harbor-image-signing`;
`rotationPolicy: Never` retains it across certificate renewals. This key is
separate from Harbor's authentication-token signing key. No AWS signing key or
public transparency log is used.

The protected publisher verifies both pushed digests, instantiates the fixed
Job template with those references, and waits for successful completion. The
Job imports the mounted PKCS8 key into Cosign's format in a memory-backed
volume, signs both digests, and returns only the public key through Pod status.
CI verifies both stored signatures with that public key before reporting success;
it does not read the signing Secret. The existing publisher robot password
protects the temporary Cosign key and authenticates registry writes. Cosign
requires its password through `COSIGN_PASSWORD`; this CI Job injects that
credential from a Secret, while the key and registry credentials remain mounted
files. No new SSM parameter or cloud permission is needed.

The pinned upstream Cosign image is independent of Harbor. The Job has no
Kubernetes API token, runs as non-root with a read-only root filesystem, and
can reach only cluster DNS and Istio HTTPS. Public signing configuration,
transparency-log upload and ambient OIDC signing are explicitly disabled.
Harbor-compatible signature attachments stay with the private images.
A 300-second deadline, zero retries and a ten-minute finished-Job TTL bound
execution and remove temporary key material with the Pod.

After merging, wait for Argo to reconcile the Certificate, registry credential
projection and network policy before publication. A failed Job or signature
verification fails CI and withholds success; images already pushed may remain
unsigned. Retry the protected publication after correcting the cause. Historical
images are not retroactively signed, and signature enforcement is not enabled.

### Public key, backup and recovery

An operator can extract the public key locally from the certificate, then use
it for independent verification (requires `kubectl`, `openssl`, and Harbor login):

```sh
kubectl -n harbor get secret harbor-image-signing \
  -o 'jsonpath={.data.tls\.crt}' | base64 --decode |
  openssl x509 -pubkey -noout > /tmp/harbor-signing.pub
nix develop --command cosign verify --key /tmp/harbor-signing.pub \
  --insecure-ignore-tlog --new-bundle-format=false \
  'harbor.stinkyboi.com/homelab/homelab-nofx-backend@sha256:<digest>'
```

The operator command's Kubernetes client receives the Secret; run it only on a
trusted operator host. CI uses Pod status instead. Keep a trusted copy of the
public key outside the cluster for historical verification. The transparency-log
flag skips only the intentionally absent public log; signature, digest and TLS
verification stay enabled. Signing does not prove an image is vulnerability-free.

The private key is recoverable secret material, so Kubernetes administrators and
any principal allowed to create Pods in `harbor` can use it. Do not delegate
those permissions to untrusted users. Include the Secret in the existing
[encrypted off-node etcd backup](../../docs/talos-etcd-backup.md) recovery set,
and verify a fresh backup after the first key is issued. Harbor's PostgreSQL
dump does **not** contain this key. Restore the original Secret before resuming
cert-manager/signing after disaster recovery; deletion otherwise generates a
new key and changes signer identity. Key loss prevents future signatures under
the old identity, but retained public keys still verify existing signatures.

Rotate through a reviewed new Secret/Certificate and explicit trust-key update;
retain old public keys and signatures. To stop new signing, revert the publishing
change while retaining the Secret and its backup. Do not delete the key as
rollback cleanup. Live backup and signature acceptance are tracked in the
[Harbor knowledge-base note](../../docs/knowledge-base/operations/harbor-oci.md).
