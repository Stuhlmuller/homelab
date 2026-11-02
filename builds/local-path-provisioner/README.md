# Local-path provisioner controller rebuild

Rancher's stable v0.0.37 ships a static controller built with Go 1.26.5. A fresh
November 2, 2026 scan found 15 fixable HIGH findings on each Linux amd64 and
arm64 child, including the standard library, `x/net`, `x/text` and `compress`.
The currently declared v0.0.36 image retained a Go toolchain and had 28 unique
fixable HIGH findings per architecture. Both gates found zero CRITICAL tuples.

This recipe builds Rancher's v0.0.37 source at `49b2be8e` with Go 1.27.3. Its
reviewed module patch selects `x/net` 0.60.0, `x/text` 0.42.0 and `compress`
1.18.7. Go resolves the corresponding indirect module versions. It downloads
modules against the patched `go.sum`, verifies them, and runs the upstream
controller unit tests. The build excludes the original vendored dependency tree
and compiles with `-mod=readonly`.

Each scratch image has one deterministic tar layer with `/usr/bin/local-path-provisioner`,
the SHA-256-verified upstream CA bundle, and license notices for the controller,
Go, and linked modules. The immutable input digests and tool releases are in
[source.json](source.json) and the dependency changes in
[dependencies.patch](dependencies.patch).

## Build and scan locally

Use the repository's Nix environment on Linux amd64/arm64 or macOS arm64. The
build downloads and verifies the pinned Go toolchain for the host. Install the
official [Trivy 0.72.0 release](https://github.com/aquasecurity/trivy/releases/tag/v0.72.0)
for that host. The scanner checks its executable SHA-256 before use.

```sh
work=$(mktemp -d)
nix develop --command python3 -I builds/local-path-provisioner/build.py \
  "$work/image" "$work/cache"
nix develop --command python3 -I builds/local-path-provisioner/scan.py \
  "$work/image" "$work/reports" --trivy /path/to/trivy
cat "$work/reports/receipt.json"
```

The output layout and report directory must be new. The cache retains verified
public archives, modules, and compiler objects for a repeat build. `regctl`
reads the public CA source anonymously and writes both images and their index
to the local OCI layout. Run the commands as an ordinary user with public
HTTPS access.

The scan resolves the official public vulnerability database by digest, checks
its update time, and exports each immutable image. It checks the exported
config and layer bytes, controller payload, exact startup configuration,
compiler version, embedded repaired module sums, and the complete versioned
Go dependency inventory reported by Trivy. Private scanner configuration,
working directory and an empty ignore file prevent caller policy from filtering
findings. A fixable HIGH or CRITICAL finding or incomplete package inventory
fails the command. Detailed JSON stays in the private output directory. A
successful receipt binds the index, child manifests, configs, binary/module
graph hashes, scanner, database revision, package counts and reports.

Both rebuilt children passed against the November 2 database, each with 53
versioned Go packages. Unfiltered scans retained two UNKNOWN findings on each
architecture. A second build reproduced the same index and child
manifests. See the [immutable artifact evidence](../../docs/evidence/local-path-provisioner-rebuild-2026-11-02.json).

## Promotion and rollback

The recipe produces a local candidate for `homelab` private-image publication.
Promotion requires a reviewed publisher, verification of the same OCI digest
and both child pulls, and a declared pull-secret contract for `cordium-storage`.
The storage Application currently selects the upstream controller.

A later consumer change must preserve its `cordium-local` provisioner name,
`WaitForFirstConsumer` and `Delete` behavior, the `zimaboard-1` restriction and
`/var/lib/cordium-workspaces` path, helper configuration, and controller
security context. The v0.0.37 chart introduces HTTP startup/liveness `/health`
and readiness `/ready` on port 8080. Readiness lists ConfigMaps, Pods, PVCs,
PVs and StorageClasses under the existing RBAC rules.

Record the bound claim, PV UID, node/path and read-only access to existing
Workspace data before and after an authorized rollout. Confirm Argo reconciliation,
controller readiness and stable volume access. Roll back the controller image
and chart revision through the storage Application while retaining the bound
PVCs, PVs and their data.
