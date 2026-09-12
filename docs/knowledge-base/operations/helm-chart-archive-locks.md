# Helm chart archive locks

Related: [[validation-gates]], [[../runbooks/image-automation]].

## Boundary

`scripts/ci/helm-chart-archives.json` binds each reviewed public Helm
repository/chart/version tuple to the SHA256 of its downloaded `.tgz` archive.
`scripts/ci/render-helm-sources.sh` requires an exact lock before downloading,
then rehashes fetched or cached bytes before handing the archive to Helm for
extraction/rendering. Missing identities, stale versions, duplicate records,
malformed digests and altered archives fail the inventory operation.

This protects **CI rendering**, including vulnerability-inventory generation.
It does not change Argo CD's chart retrieval or enforce Argo provenance, verify
publisher signatures, establish complete SBOM coverage, or remediate image CVEs.
An empty image delta remains different from a clean vulnerability baseline.

The current reviewed lockfile and renderer apply to both current and base
source snapshots. Historical lockfiles are not silently trusted. Keep approved
older-version entries while they are needed for supported base comparisons;
an otherwise valid unused entry is not an error. A source changed to a new
repository, chart or version must have its own reviewed lock. This is the
stale-lock failure that the fixtures exercise.

## Initial trust and scope

Initial hashes were collected on 2026-09-06 UTC from PR #930's exact source
`9ca34c75492f6f3467db3ba761bfa4fb1d47b5ba`, using its existing isolated public
Helm downloader. Native Terragrunt/Kustomize discovery found 29 Helm invocations:
20 distinct packaged charts (17 HTTPS repositories, three OCI repositories)
and one already commit-pinned local-path Git source, with repeated charts reused.
The Git source retains its existing exact commit check before extraction;
this change does not replace it with a chart archive lock.

The OCI charts are Compass `0.6.0`, LiteLLM `0.1.832`, and Multica `0.4.29`.
Their locks hash the Helm `.tgz` payload, **not the OCI registry manifest**.
All repositories, chart names, versions and payload hashes are explicit in the
JSON file. No chart version, image reference or rendered workload is upgraded.

These hashes attest the downloaded bytes reviewed with this change. The first
capture trusts the repository's already-declared public distribution endpoints
and HTTPS transport; a checksum from the same endpoint is not independent
publisher authentication. No signature verification is claimed. A compromised
upstream at first capture would need separate provenance/source investigation.

## Updating a lock

1. Review the intended source/version change and its upstream release evidence.
2. Download that exact chart into a new empty directory without credentials or
   plugins. This copyable HTTPS example uses explicit public placeholders; for
   OCI, replace `--repo ... -- CHART` with `-- oci://REGISTRY/PATH/CHART`:

   ```sh
   nix develop --command bash -c '
     set -euo pipefail
     scratch=$(mktemp -d)
     trap '\''rm -rf -- "$scratch"'\'' EXIT
     mkdir "$scratch/empty" "$scratch/archives"
     env -i PATH="$PATH" HELM_PLUGINS="$scratch/empty" \
       DOCKER_CONFIG="$scratch/empty" \
       helm --kubeconfig /dev/null \
       --registry-config "$scratch/empty/registry.json" \
       --repository-config "$scratch/empty/repositories.yaml" \
       --repository-cache "$scratch/empty" pull \
       --repo https://PUBLIC-REPOSITORY \
       --version EXACT-VERSION --destination "$scratch/archives" -- CHART
     sha256sum "$scratch/archives/"*.tgz
   '
   ```

3. Inspect the archive/source evidence, add its exact tuple/hash to the JSON
   lockfile, and review the lock alongside the source change. Do not replace an
   existing tuple's hash merely because CI reports drift: investigate changed
   upstream bytes first. There is no automatic lock regeneration or acceptance.
4. Run renderer self-checks, the full inventory, the relevant base comparison,
   and repository validation. Compare rendered manifests when no runtime change
   is intended. Missing historical locks require explicit review, not a bypass.

```sh
nix develop --command bash scripts/ci/render-helm-sources.sh --self-check
nix develop --command bash scripts/ci/image-vulnerability-scan.sh --list
nix develop --command bash scripts/ci/image-vulnerability-scan.sh --list BASE_COMMIT
nix develop --command bash scripts/ci/static-checks.sh
```

The offline fixtures prove exact-key lookup, valid cache reuse, rejection before
fetch for missing/stale identities, fetched/cached byte tampering, and invalid
or duplicate lock records. Listing renders charts but does not scan images or
change live state. Roll back through a reviewed code/lock revert; never disable
checksum checks to accept unexplained archive changes.

## September 11 integration

PR #930's rendered-image scanner stack was closed without merging. The archive
lock change therefore carries that prerequisite into `main`: native declared
workload inventory, occurrence-based image selection, the existing package and
vulnerability gate, and its pinned scanner runtime. The original baseline
reports above remain dated evidence, not current security clearance.

The renderer now accepts escaped dots and slashes in Helm parameter names,
which the existing ztunnel cutover label requires. Its native Helm regression
first rejected the committed key, then passed after the narrow grammar update;
unsupported escapes, commas, and array-index syntax still fail. Both Nix Bash
and macOS Bash 3.2 run the fixture. No live state changes through this renderer.

The older literal-inventory prerequisite also made seven image repositories
explicit in cert-manager and local-path values. Native rendering already
exposes those images. This integration preserves `main`'s runtime values and
omits that superseded workaround; the scanner's occurrence-count and image
validation rules remain unchanged. Both revisions are rendered by the same
current helper before selecting their image delta.

Full native rendering also exposed the scanner's old blanket rejection of
Kiali additional containers. The source-verified `v2.26.0` contract now includes
explicitly allowed, typed init/sidecar image fields. It preserves the existing
Prometheus readiness init container. A native render of current Kiali values
extracts the operator, generated server and pinned Curl image; regressions
reject disallowed additions, malformed arrays, missing/invalid images and
duplicate container names. See [[validation-gates]] for the upstream contracts.
