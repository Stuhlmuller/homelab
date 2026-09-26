# Maintained NOFX images

This recipe rebuilds the pinned NOFX release with passive, key-preserving model
configuration, validated backtest run IDs, OKX US public historical candles,
and the allocated cash-spot executor described below. Historical decisions
exclude current quant/ranking feeds and use the simulated clock for position
age. OKX construction reads account mode without trying to change it.
Preparing or building these images does not enable live traders. Deployment
and operational acceptance are documented in the
[NOFX runbook](../../clusters/homelab/apps/nofx/README.md).

Historical runs using `openrouter/free` at the official OpenRouter API request
strict structured decisions and require a provider that supports those request
parameters. Malformed responses remain failed cycles instead of becoming
synthetic `ALL` wait decisions. This strict path makes one provider attempt per
cycle, including transient errors; failures remain visible. Other models and
live traders retain their existing request path. The simulator also caps actual
fill leverage at the configured limit.

Patch `0013-litellm-runtime-routing.patch` preserves NOFX's encrypted provider
configuration and routes only `openrouter/free` through LiteLLM when the fixed
mounted JSON config exists. It reads the gateway bearer from the declared token
file, sends the original provider key only in the gateway request body, and uses
no environment-variable routing inputs. The source change is inert until a
reviewed `main` build publishes an exact backend image digest; do not change the
active deployment digest as part of the configuration-only rollout.

Normal trader decision parsing preserves the shared validator's leverage clamp
in the returned decisions. Trader creation also preserves an explicit hidden
leaderboard setting; the API retains its visible default when omitted. Focused
parser and SQLite regressions run in the backend image's test stage. The legacy
OKX futures adapter from patch `0009` reads current cross-margin leverage and
skips the write when it already matches. Otherwise it makes one instrument-level
leverage request, following the [OKX API guide](https://www.okx.com/docs-v5/trick_en/).
Missing or malformed current-leverage data, or failed leverage requests, stop
opening orders before canceling existing orders. Mocked transport checks cover
both directions.
Those futures paths remain in the source for regression coverage; patch `0012`
replaces every runtime OKX construction with cash spot. Arena's separate
consensus execution path is rejected by the cash-spot adapter.

Patch `0011` routes the OKX adapter through `https://us.okx.com` for this
homelab's confirmed US account. All signed REST calls share that constant;
there is no automatic regional fallback. Patch `0011` alone does not add spot
trading or establish eligibility for USDT perpetuals. Keep traders stopped.
Dashboard reads return a typed, safe HTTP 503 when an owned saved trader cannot
load; missing or foreign traders return 404. The UI displays the load guidance
without claiming the API route is missing. Patch `0012` withholds legacy OKX
whole-account equity history; other equity history remains database-only.
Handler, transport, and Axios regressions run in the existing image test targets.

Backtest Lab compares selected runs using recorded equity, return, drawdown,
and decision outcomes. The table does not infer a valid score from Completed:
review decision completeness, matching inputs, and executed leverage as described
in the [competition runbook](../../docs/nofx-agent-competition.md). Newly generated
run IDs include a safe strategy slug. Keep rounds uninterrupted: cold resume
still does not reliably restore the selected strategy snapshot, so start fresh
matched runs after a backend restart.

## OKX US cash-spot competition

Patch `0012` replaces this installation's OKX runtime construction with the
cash-spot adapter and adds a stopped-only capital-allocation form. The
[regional API contract](https://app.okx.com/docs-v5/en/) defines its US host,
cash orders, account fee currency, and native OCO protocol. It uses one
server-verified account identity across connection aliases. Decimal reservations
and append-only fills own each agent's cash, inventory, fees, and cost basis;
legacy account positions and balances cannot become competition performance.
The shared cap limits outstanding buy reservations plus owned inventory's
acquisition cost; it is not a ceiling on marked market value or a loss guarantee.
Each trader is also limited by its own remaining quote cash and strategy limits.

This is prepared source, not a verified cash-spot deployment. Publish the exact
reviewed main commit to private Harbor, pin its reported backend/frontend
digests through a separate rollout PR, then verify readiness, served source,
and stopped-state acceptance. Explicit capital amounts remain an operator input;
this change neither chooses them nor starts a trader.

The existing single backend replica is the execution boundary: a process lock
serializes account reconciliation and submission; database transactions reserve
funds before HTTP. More than one execution process requires a durable execution
lease first. Do not increase backend replicas without that change.

Mocked protocol, SQLite concurrency, restart/replay, lifecycle, and UI checks run
in the image test stages. Manager checks cover unavailable scores and bounded
refresh; lifecycle and recovery tests cover stopped execution and saved OCO
ownership. Tests use synthetic credentials and mocked exchange transports;
they send no live orders. No dependencies are changed by patch `0012`.
See the [competition runbook](../../docs/nofx-agent-competition.md#one-okx-account)
for execution limits, current-data ranking, and operator activation.

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

After publication succeeds, a separate job with no repository permissions or
production credentials validates exactly one backend and one frontend reference
for that workflow's source revision. It uploads only `nofx-published-images.txt`
as `nofx-published-images-<full-main-sha>`, retained for 30 days. Download it with
the signed-in CLI, then use its two references in the reviewed runtime-pin PR:

```sh
gh run download <successful-run-id> --repo Stuhlmuller/homelab \
  --name nofx-published-images-<full-main-sha> --dir /tmp/nofx-published-images
cat /tmp/nofx-published-images/nofx-published-images.txt
```

The report is generated only from verified publication outputs; it never uploads
registry authfiles, transport logs, or the publisher workspace. The existing
Actions step summary remains available. Artifact expiry does not delete images;
a missing report is not permission to infer digests from mutable tags.

The live NOFX overlay is intentionally inert until
[`activate-nofx.patch`](../../docs/examples/langfuse/activate-nofx.patch) is
applied. Before applying it, require activated LiteLLM, a Ready `nofx-litellm`
ExternalSecret with its target Secret present, and a reviewed `main` publication
of an image containing `0013-litellm-runtime-routing.patch`. Then pin that
verified backend digest in a separate rollout; do not change the current digest
as part of staging. Afterward, run a short historical
`openrouter/free` simulation through LiteLLM and inspect the result for one
structured provider attempt and no credential-bearing log output.
That activation follow-up also consumes the patch, removes its scratch apply
check, and makes `nofx-runtime-check.py` validate the active route directly.

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

At the migration inventory check, NOFX still used upstream images. The
successful [migration](https://github.com/Stuhlmuller/homelab/actions/runs/35486238550)
preserved all historical digests and verified complete read-only pulls. The
initial maintained rollout then selected the migrated `f76c278` pair in
[PR #1036](https://github.com/Stuhlmuller/homelab/pull/1036). Preserve those
artifacts as recovery history; a later source build requires its own verified
publication and functional acceptance.

Use [deployment.yaml](../../clusters/homelab/apps/nofx/deployment.yaml) for the
current desired image references, rather than copying this historical migration
inventory. Pin both published images in a separate reviewed rollout PR with
`harbor-pull`, then verify ready Pods at both exact digests. Follow the
[rollout gates](../../docs/nofx-private-images.md#harbor-runtime-acceptance),
including a fresh authenticated `STOPPED` check before merge. Keep Harbor
repositories private and retain old artifacts until consumers have moved to
another verified pair through reviewed desired state.

The retained GHCR packages remain private. Their recovery pull credential is
covered by the [private-image runbook](../../docs/nofx-private-images.md).
Do not change package visibility to work around a missing pull credential.

For an upstream update, change the source revision and archive checksum together,
review the runtime/builder digest compatibility, rebase the patches, and require
both test and build commands to pass. Preserve historical-source provenance:
new UI runs select `okx_us`, while older saved runs without a source keep Binance.

To revert a build change, revert its recipe/patch commit through a PR and publish
the resulting new commit tag. To roll back deployment, stop simulations and
all live traders, review unresolved submissions and native protective orders,
then restore the previous reviewed image digests through GitOps. Retain
`nofx-data`, including the additive spot tables and append-only fill history,
and the absolute executable/working-directory configuration. Never reset the
ledger to make a rollback load. Earlier images cannot reconcile that ledger;
keep every OKX trader stopped while running them. Returning to upstream also
restores its model-save side effects and Binance dependency.

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
CI checks that public key against the reviewed SHA-256 fingerprint in
`scripts/config/harbor-signing.json`, then verifies both stored signatures;
it does not read the signing Secret. The existing publisher robot password
protects the temporary Cosign key and authenticates registry writes. Cosign
requires its password through `COSIGN_PASSWORD`; this CI Job injects that
credential from a Secret, while the key and registry credentials remain mounted
files. No new SSM parameter or cloud permission is needed.

The pinned upstream Cosign image is independent of Harbor. The Job has no
Kubernetes API token, runs as non-root with a read-only root filesystem, and
declares only cluster DNS and Istio HTTPS egress in its NetworkPolicy. The
current flannel CNI does not enforce that policy, and Harbor is not mesh-enrolled:
compromised signing code could send the mounted key and publisher credential
to arbitrary destinations. Treat the pinned signer as trusted code, not as an
egress-isolated key service. Track enforcement and a denied-egress acceptance
test in the [Harbor note](../../docs/knowledge-base/operations/harbor-oci.md#private-signing-rollout).
Public signing configuration,
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

Initial enrollment is deliberately staged: the committed fingerprint is `null`,
which blocks publication before credentials or image pushes. After Argo issues
the Certificate, use the read-only extraction below on the trusted cluster.
Run `shasum -a 256 /tmp/harbor-signing.pub` and commit that fingerprint as
`public_key_sha256` in `scripts/config/harbor-signing.json` through a reviewed PR.
The hash covers the exact PEM public-key file, including its final newline.
Then dispatch the protected publisher at the enrolled main commit. Never enroll
from a failed signing Job: independently check the retained key first.
A replacement key fails verification even if its signatures are valid. Planned
rotation requires a separately reviewed fingerprint update; accidental loss
requires restoring the original Secret, not accepting its replacement.

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
