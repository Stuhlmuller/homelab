# Image Automation And Image Updater Retirement

Renovate is the repository's image-update path. Its built-in Helm values,
Kustomize, and Kubernetes managers open reviewed pull requests for image tags
and digests. `scripts/ci/static-checks.sh` rejects every repo-declared
container image that is not pinned as `tag@sha256:digest`.

OctoBot remains limited to `2.1.1` in `renovate.json` because `2.1.13` rejects
the retained PVC-backed `config.trading.paused` value. Other compatibility and
stateful migration decisions happen during normal pull-request review.

## Vulnerability Scanning

`scripts/ci/image-vulnerability-scan.sh` extracts exact digest-pinned images
from repository-owned Kubernetes YAML, Helm values, and operator scripts.
The YAML extractor also reads Argo CD Application `spec.source.helm.values` and
`spec.sources[].helm.values` strings. A nonempty image `digest` takes precedence
over `tag`; repository-plus-digest mappings do not require a tag. Other embedded
configuration strings are not parsed as Helm values. Operator scripts contribute
literal whitespace/quote-delimited pins, not evaluated shell expressions.

The required `validate` job scans each exact image whose occurrence count increases
in a change for fixable HIGH and CRITICAL vulnerabilities. Reusing a vulnerable
baseline digest in another workload is therefore blocked. The weekly run scans
the complete extracted inventory so newly published advisories are detected
without a repository change. Existing vulnerable images remain visible in the
weekly baseline without blocking unrelated pull requests.

Inspect the inventory and test extraction locally without invoking Trivy:

```sh
nix develop --command bash scripts/ci/image-vulnerability-scan.sh --list
nix develop --command bash scripts/ci/image-vulnerability-scan.sh --self-check
```

Temporary exceptions belong in `.trivyignore.yaml`. Each exception must name
the exact package PURL, link the GitHub issue accepting the risk, and expire.
Trivy stops suppressing an expired finding, and the wrapper also rejects
expired or unscoped entries. A PURL exception applies to that package across
images, so keep its issue scope and lifetime narrow.

The development shell temporarily overrides the locked Trivy `0.69.3` package
with `0.74.0`, built with scanner-only Go `1.26.7` under #916. This includes the fix
for [CVE-2026-55092](https://github.com/aquasecurity/trivy/security/advisories/GHSA-mcj4-mphf-j9ff).
The upstream lock remains unchanged; the full refresh remains blocked under
issue #888. See [the runtime pin](knowledge-base/operations/validation-gates.md#scanner-runtime-pin)
for reproducible build evidence and removal gates. As defense in depth, the
wrapper still scans from an empty directory, ignores repository configuration,
removes named registry/database override variables, and uses the trusted default
database source. It also forces the cluster's `linux/amd64` platform.

[Issue #915](https://github.com/Stuhlmuller/homelab/issues/915) hardens that
boundary: complete image scalars are validated before line serialization,
malformed or option-shaped digest references fail before any Trivy invocation,
and `--` separates the image argument from scanner options. Extraction failures
propagate for both current and base files, including list and no-delta paths.
The self-check covers earlier invalid scalars or documents followed by valid
ones, literal shell registry ports, tagless pins, overlong digests, and the final
invocation arguments with a stub, without running Trivy.

This setup is not an OS sandbox or a local credential boundary. Other inherited
Trivy settings and GitHub, Podman, or cloud credential sources may still apply
locally. Run vulnerability scans in the unprivileged hosted `validate` gate
without operator credentials.

The cert-manager and local-path image repositories are explicit copies of their
pinned charts' effective defaults; their digests and rendered images are
unchanged. Compared with draft #905's 59-reference inventory, extraction now
lists 66 textual references representing 65 image identities: five cert-manager
images and the local-path provisioner are newly covered; the fully qualified
BusyBox helper is an alias of an already-covered image. The scanner deliberately
keeps textual references and occurrence counting unchanged.
Reverting this extraction follow-up restores the prior inventory without
changing rendered workloads.

The extractor does not invent image names for remaining remote chart defaults.
At least the [24 confirmed tag-only identities recorded in #791](https://github.com/Stuhlmuller/homelab/issues/791#issuecomment-5466003981)
remain outside this phase; that inventory is not a claim of live or complete
coverage. SBOM and signature verification remain separate follow-up work.
Extraction/list self-checks do not prove images are vulnerability-free. The
2026-08-30 uncredentialed `linux/amd64` audit with the patched scanner found
21 fixable HIGH tuples in local-path (#918) and 11-12 in each cert-manager image
(#919). BusyBox returned no package targets, so its zero findings mean unknown
coverage (#920). These existing images block acceptance; no exception was added.

Rollback by reverting the scanner, workflow, ignore file, and Nix package
change; the check writes only temporary CI/local cache and never changes live
cluster state.

## Why Image Updater Was Retired

Argo CD Image Updater had been unable to push since May 2026 because its GitHub
App bot had no repository permission. Its stale Radarr selector also allowed
only `5.x` while desired state was already pinned to `6.3.0`, so a successful
reconcile could have proposed a downgrade. Renovate already covered the same
repository sources without a second controller or write credential.

## Safe Retirement Sequence

The retirement is safe if the Terragrunt apply is delayed or unavailable:

1. The existing live Application still reads
   `clusters/homelab/apps/argocd-image-updater/values.yaml` from `main`.
   Merging sets its controller Deployment to zero replicas.
2. The same Application auto-syncs the marker-only Kustomize source with prune
   enabled. That removes the `homelab-managed-images` custom resource and the
   `argocd-image-updater-git` ExternalSecret. The generated Secret is removed
   with its owning ExternalSecret.
3. The post-merge Terragrunt apply changes the Application to the marker-only
   source. Argo CD then prunes the remaining Helm resources. The removed
   `ImageUpdater` is sync wave `1`; the chart CRD is wave `0`. Argo CD prunes
   higher waves first and stops before lower waves if a prune fails, so the CR
   is gone before the CRD can be removed even if this apply wins the race with
   the first auto-sync.
4. The same Terragrunt workflow applies the SSM unit and removes the retired
   parameter paths from the External Secrets reader IAM policy. The parameters
   themselves remain state-managed tombstones.

Keep the inert Application, ConfigMap, zero-replica values file, and lock file
until Argo CD reports the marker revision synced and the retired controller
resources are absent. A later reviewed change may then remove the Terragrunt
unit and retirement directory.

The three `/homelab/argocd-image-updater/github-app/*` SSM parameters have no
runtime consumer or External Secrets reader IAM grant. They remain declared
only as OpenTofu state tombstones because the production policy rejects SSM
parameter deletion. Retire those values and state through a separate reviewed
secret-retirement workflow.

## Verification

Before the Terragrunt Application update has applied, expect zero desired
controller replicas and no active selector or credential consumer:

```sh
kubectl -n argocd get deploy argocd-image-updater-controller
kubectl -n argocd get imageupdater homelab-managed-images
kubectl -n argocd get externalsecret argocd-image-updater-git
```

After the Terragrunt apply and Argo CD sync:

```sh
argocd app get argocd-image-updater
kubectl -n argocd get configmap argocd-image-updater-retirement
kubectl -n argocd get deploy,serviceaccount,role,rolebinding \
  -l app.kubernetes.io/instance=argocd-image-updater
kubectl get clusterrole,clusterrolebinding \
  -l app.kubernetes.io/instance=argocd-image-updater
kubectl get crd imageupdaters.argocd-image-updater.argoproj.io
```

Expected result: the Application is `Synced` and `Healthy`, only the retirement
ConfigMap remains managed by it, and the retired controller resources are
absent. Do not delete the Terragrunt unit before this check passes.

## Rollback

Before the marker-only Application update, revert the retirement commit so the
existing Application restores its chart values and manifests. After that
update, revert and apply the restored Terragrunt unit so Argo CD owns the chart
again. Reintroducing the controller also requires a reviewed, working write
credential and corrected selectors; do not restore the broken contract merely
to preserve the old topology.
