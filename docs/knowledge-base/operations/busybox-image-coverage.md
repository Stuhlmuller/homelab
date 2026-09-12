# BusyBox Image Coverage

Tags: #operations #security #storage

Related: [[continuous-improvement]], [[validation-gates]], [[storage-and-state]].

## Finding and Scope

Research for [#920](https://github.com/Stuhlmuller/homelab/issues/920),
2026-08-30, repository base `021a510698be3e7f88bd672301717e4f6e76841b`.
Keep the coverage guard and current helper pin: the Alpine candidate fails the
vulnerability policy, and the one Chainguard alternative is not a drop-in.
Any eventual replacement is **local-path helper only**; other BusyBox callers
remain separate work. This research reads separately collected scan evidence
and public source/metadata. It ran no additional scans, image execution, layer
downloads, authentication or live changes.

The audited reference is
`docker.io/library/busybox:1.38.0@sha256:fd8d9aa63ba2f0982b5304e1ee8d3b90a210bc1ffb5314d980eb6962f1a9715d`.
Its `linux/amd64` child is
`sha256:1cfa4e2b09e127b9c4ed43578d3f3c18e7d44ea47b9ea98475c0cbe9086525f8`.
The saved Trivy `0.74.0` report has no detected OS or `Results` field:
zero findings mean unknown coverage. The current `1.38.0` index `dc2d74…`
contains the same amd64 child, so refreshing that index alone changes neither
its filesystem nor this coverage gap. See [historical published metadata][busybox-old]
and [current tag metadata][busybox-current].

## Why the Image Has No Package Targets

The [historical Official Images mapping][busybox-map] selects the glibc variant
and OCI-import build. Its [builder recipe][busybox-builder] compiles BusyBox
`1.38.0`, then constructs a separate root filesystem with BusyBox applets,
Debian `getconf`, copied glibc/NSS libraries, and Buildroot account files.
It does not copy Debian's package database or OS-release files. The
[export script][busybox-build] publishes only that root filesystem.
The image history's “Debian 13” describes its builder, not an installed Debian
package inventory. This explains the saved scanner result; it is not evidence
that BusyBox or its copied libraries are vulnerability-free.

An upstream SBOM **does exist**. The exact index links amd64 attestation manifest
`sha256:ffc88d62b497c8e4787c05bc8217822b61327f01ac264b380e1ee939202675b2`
to SPDX blob
`sha256:7270b3e1860ce241a82985a86c3d412264e15d7764c22ac3085a0ab39232fcea`.
Public cached metadata was retrieved without credentials; index, manifest and
blob SHA-256 values matched. The [SPDX statement][busybox-sbom], attributed to
Docker Scout `1.18.1`, contains a document-root entry and only
`pkg:generic/busybox@1.38.0`, evidenced by `bin/busybox`'s checksum and layer.
It has no glibc/getconf package inventory. Its `subject` is empty; the association
is the [index's attestation descriptor][busybox-index], not verified signing
identity. That manifest contains no SLSA provenance predicate; separate
provenance/signature availability was not established.

Source inspection also shows Trivy's [PURL classification][trivy-purl] and
[SBOM decoder][trivy-sbom] skip unsupported generic package types. Thus this
SPDX file is not a demonstrated Trivy vulnerability target or complete runtime
SBOM. A trustworthy SBOM route would need digest-bound, scanner-supported
identities and evidence for the copied libraries too. Do not manufacture distro
metadata, relabel the generic entry as an APK, or exempt empty reports.

## Alpine Candidate: Rejected

The separately audited candidate is `docker.io/library/alpine:3.24.1`,
the current stable/latest patch on
[Alpine's release page][alpine-releases], supported through 2028-06-01.
The [Official Images source mapping][alpine-map] points to source commit
`398ff0c866d27e9f46f53e48184fe36c674b8897`.

- Index: `sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b`.
- Linux/amd64: `sha256:79ff19e9084a00eece421b2523fb93e22d730e2c0e525905de047e848e56d95f`.
- [Published image metadata][alpine-remote] matches image ID
  `sha256:d529dd0c6e5597ac7e4a3e2dea65c3fcc6173f4cae713c409265c1dd9914a11b`;
  [installed-package metadata][alpine-packages] lists BusyBox `1.37.0-r31`,
  `busybox-binsh`, musl and APK `3.0.6-r0`, with `/bin/sh` as the default command.

This is a packaged BusyBox **1.38 → 1.37** and glibc → musl change, not a
same-binary update. Alpine's [vendor advisories][alpine-secdb] track distro
revision backports; compare those revisions, not upstream version numbers alone.
Applet behavior and filesystem permissions remain untested. Extra distro
packages also increase scan surface.

The 2026-08-30 uncredentialed `linux/amd64` audit with Trivy `0.74.0`/Go `1.26.7`
recognized Alpine `3.24.1` and **16 packages**, including BusyBox `1.37.0-r31`
and musl `1.2.6-r2`. It exited **1** under the unchanged fixable HIGH/CRITICAL
policy: **two HIGH package-level findings, zero CRITICAL, one unique CVE**.
`CVE-2026-14456` affects both `libcrypto3` and `libssl3`, installed `3.5.7-r0`,
fixed `3.5.8-r0`, from Alpine Secdb. These are package/version matches, not proof
of helper-command exploitability. The [3.24 vendor feed][alpine-secdb] records
the OpenSSL fix. The candidate is not accepted; no helper execution or pin
change followed.

Actual findings plus [exact release-stream lookup][trivy-alpine] establish
Alpine 3.24 advisory namespace availability, not exhaustive advisory coverage.
Trivy's EOL map stopping at 3.23 explains the warning; it did not prevent
package detection or this lookup. An older Alpine branch is not justified by
that stale table. Retained local evidence, not committed:

- `/private/tmp/homelab-alpine-920.pQbAtj/alpine-report.json`, SHA-256
  `55196032931b3d7246cadaf9de1d7388df2dd0de7b7cd34c2dfd14cb57738ae8`.
- `/private/tmp/homelab-alpine-920.pQbAtj/audit-evidence.json` records invocation,
  exit status, database metadata, source inspection and coverage limitations.

## One Alternative: Chainguard BusyBox, Not a Drop-in

The [current public directory][chainguard-overview] offers
`cgr.dev/chainguard/busybox:latest` / `latest-glibc` as free Starter images.
[Free-image access][chainguard-access] does not require an account; specific
versioned tags require a different entitlement. This is not the separate,
account-based Catalog Starter plan. [Lifecycle documentation][chainguard-life]
limits the free tier to latest builds with no patch SLA; indefinite historical
digest availability for rollback was not established. Package licenses remain
applicable: the public [SBOM view][chainguard-sbom] lists BusyBox GPL-2.0-only
and glibc LGPL-2.1-or-later. No commercial entitlement or terms were accepted.

Current documentation describes **Wolfi/glibc**, not musl. The
[specifications][chainguard-specs] show a shell, no APK CLI, and default
**UID 65532**. The SBOM view exposes versioned Wolfi APK identities for BusyBox
and glibc; absence of the APK executable does not establish absence of a
package database. However, the unversioned pages showed differing BusyBox
versions, and the unauthenticated registry manifest request returned HTTP 401.
No token exchange was attempted. Exact public index/amd64/config digests,
bound SBOM, OS/package database and applet behavior therefore remain unverified.

Stop this candidate here: UID 65532 does not preserve the current helper's root
hostPath write/delete contract. It would require a separately reviewed helper
user/template change, immutable artifact resolution, positive scanner coverage,
policy-passing results and exact script tests. It is not a safe two-value pin
replacement, and no clean-image claim follows from the vendor's directory.

## Helper Contract and Other Callers

At Rancher commit `5d4bfc84b32cd9c5f56ed3aba921b1a3924ea2f0`, the
[controller][helper-code] invokes `/bin/sh /script/setup` or `/script/teardown`
with `-p <path> -s <bytes> -m <mode> -a create|delete` and environment values
`VOL_DIR`, `VOL_SIZE_BYTES`, `VOL_MODE`. The [default scripts][helper-values]
use `set -eu`, `mkdir -m 0777 -p "$VOL_DIR"`, and `rm -rf "$VOL_DIR"`.
The volume's parent host directory is writable; scripts mount at `/script`.
The [helper template][helper-template] has no security context: the controller's
non-root settings do not apply to it. Preserve effective root write/delete
permissions, volume-node scheduling and the existing 120-second helper budget.

The repository contains **14 container declarations, three digests, four textual
references**. Nothing calls the `busybox` binary directly; shell/applet contracts
matter. `fd8d9aa…` has seven short-name aliases plus the fully qualified helper;
`dc2d74…` uses `busybox:1.38.0`, and `9532d8…` uses `busybox:1.37.0`.

- `fd8d9aa…`, one [local-path helper][repo-helper]: shell, mkdir/rm,
  writable hostPath and root permissions.
- `fd8d9aa…`, three backup CronJobs: [Deluge][backup-deluge],
  [Radarr][backup-radarr], [Sonarr][backup-sonarr]. UID/GID 1000, read-only
  root/source; gzip tar create/list/extract, grep, find/delete and atomic mv
  on backup NFS.
- `fd8d9aa…`, two [Cordium sysctl init/status containers][sysctl]: privileged
  UID 0 write, non-root status read; shell, printf, cat and long sleep.
- `fd8d9aa…`, one [Grafana backup init][grafana]: UID/GID 472, cp -p, cmp,
  mv; preserve existing backup.
- `fd8d9aa…`, one [Octelium WAL recovery init][octelium]: writable retained
  data, mv/touch; preserve dated quarantine and marker.
- `dc2d74…`, three media init values: [Deluge][init-deluge],
  [Radarr][init-radarr], [Sonarr][init-sonarr]. mkdir on downloads;
  chown 1000:1000 with CHOWN capability on config.
- `9532d8…`, three retained migration Jobs: [downloads][migration-deluge],
  [movies][migration-radarr], [TV][migration-sonarr]. UID/GID 65534,
  cp -R and chmod -R; no durable completion marker. Do not recreate casually.

## Next Acceptance Evidence

1. Keep both candidates unaccepted. For a subsequently approved replacement,
   resolve its immutable artifact and require an uncredentialed `linux/amd64`
   scan under the pinned runtime and unchanged fixable HIGH/CRITICAL policy.
   Retain fresh JSON, package versions, OS/release, DB metadata and exit status;
   require positive coverage including BusyBox and libc, not merely no findings.
2. In an isolated disposable filesystem, execute the exact helper scripts with
   their arguments/environment as root; verify create mode 0777, existing-path
   idempotence, teardown and preservation of a sibling directory. Confirm the
   image's user, architecture and shell. No live hostPath tests at this stage.
3. Only after those checks, propose a helper-only change in
   [the existing Application][repo-helper], plus affected docs. A compatible
   image-only replacement needs two `helperImage` values; Chainguard would also
   need a reviewed helper-user/template change. Render the exact pinned chart
   and run repository gates. Leave controller/chart versions, storage class,
   node/path restrictions and the other 13 declarations outside this change.
4. Separately authorize the declared GitOps rollout and a disposable-PVC
   create/delete/recreate check. Keep `cordium-local`, `zimaboard-1`,
   `/var/lib/cordium-workspaces` and `Delete` reclaim policy unchanged. Roll back
   the helper pin through git if needed; that cannot recover deleted scratch
   data. The existing [storage contract][storage] remains authoritative.

[busybox-old]: https://github.com/docker-library/repo-info/blob/669084933cb2a8e1d066af8f4f52e2513d05c9d9/repos/busybox/remote/1.38.0.md
[busybox-current]: https://hub.docker.com/v2/namespaces/library/repositories/busybox/tags/1.38.0
[busybox-map]: https://github.com/docker-library/official-images/blob/da3b030b9dd58f7cb1cd0063a96984c2686ffd5f/library/busybox
[busybox-builder]: https://github.com/docker-library/busybox/blob/7d88ac3f2be7fdef1fdcb0d11488f3adf615e2a1/latest/glibc/Dockerfile.builder
[busybox-build]: https://github.com/docker-library/busybox/blob/7d88ac3f2be7fdef1fdcb0d11488f3adf615e2a1/build.sh
[busybox-sbom]: https://mirror.gcr.io/v2/library/busybox/blobs/sha256:7270b3e1860ce241a82985a86c3d412264e15d7764c22ac3085a0ab39232fcea
[busybox-index]: https://mirror.gcr.io/v2/library/busybox/manifests/sha256:fd8d9aa63ba2f0982b5304e1ee8d3b90a210bc1ffb5314d980eb6962f1a9715d
[trivy-purl]: https://github.com/aquasecurity/trivy/blob/v0.74.0/pkg/purl/purl.go#L200
[trivy-sbom]: https://github.com/aquasecurity/trivy/blob/v0.74.0/pkg/sbom/io/decode.go#L192
[trivy-alpine]: https://github.com/aquasecurity/trivy/blob/v0.74.0/pkg/detector/ospkg/alpine/alpine.go#L69
[alpine-releases]: https://alpinelinux.org/releases/
[alpine-map]: https://github.com/docker-library/official-images/blob/master/library/alpine
[alpine-remote]: https://github.com/docker-library/repo-info/blob/a9c07b1fadc5ead9198cedf3bb0ec8225ec851fe/repos/alpine/remote/3.24.1.md
[alpine-packages]: https://github.com/docker-library/repo-info/blob/a9c07b1fadc5ead9198cedf3bb0ec8225ec851fe/repos/alpine/local/3.24.1.md
[alpine-secdb]: https://secdb.alpinelinux.org/v3.24/main.json
[chainguard-overview]: https://images.chainguard.dev/directory/image/busybox/overview
[chainguard-access]: https://edu.chainguard.dev/chainguard/containers/overview/
[chainguard-life]: https://edu.chainguard.dev/chainguard/containers/about/versions/
[chainguard-sbom]: https://images.chainguard.dev/directory/image/busybox/sbom
[chainguard-specs]: https://images.chainguard.dev/directory/image/busybox/specifications
[helper-code]: https://github.com/rancher/local-path-provisioner/blob/5d4bfc84b32cd9c5f56ed3aba921b1a3924ea2f0/provisioner.go#L624
[helper-values]: https://github.com/rancher/local-path-provisioner/blob/5d4bfc84b32cd9c5f56ed3aba921b1a3924ea2f0/deploy/chart/local-path-provisioner/values.yaml#L167
[helper-template]: https://github.com/rancher/local-path-provisioner/blob/5d4bfc84b32cd9c5f56ed3aba921b1a3924ea2f0/deploy/chart/local-path-provisioner/templates/configmap.yaml#L36
[repo-helper]: ../../../clusters/homelab/platform/storage/cordium-local-path-provisioner-application.yaml
[backup-deluge]: ../../../clusters/homelab/apps/deluge/backup-cronjob.yaml
[backup-radarr]: ../../../clusters/homelab/apps/radarr/backup-cronjob.yaml
[backup-sonarr]: ../../../clusters/homelab/apps/sonarr/backup-cronjob.yaml
[sysctl]: ../../../clusters/homelab/apps/cordium/user-namespace-sysctl.yaml
[grafana]: ../../../clusters/homelab/apps/grafana/values.yaml
[octelium]: ../../../clusters/homelab/apps/octelium-enterprise/resources.yaml
[init-deluge]: ../../../clusters/homelab/apps/deluge/values.yaml
[init-radarr]: ../../../clusters/homelab/apps/radarr/values.yaml
[init-sonarr]: ../../../clusters/homelab/apps/sonarr/values.yaml
[migration-deluge]: ../../../clusters/homelab/apps/deluge/media-storage.yaml
[migration-radarr]: ../../../clusters/homelab/apps/radarr/media-storage.yaml
[migration-sonarr]: ../../../clusters/homelab/apps/sonarr/media-storage.yaml
[storage]: ../architecture/storage-and-state.md
