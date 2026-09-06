# Gluetun candidate image build

This path builds and validates a local Linux/amd64 candidate. It does not
publish an image, change Deluge's image pin, or modify cluster state. Complete
native Linux CI validation is still pending; local source and input checks
do not establish runtime compatibility or reproducible image output.

## Pinned inputs

- [`default.nix`](default.nix) keeps Gluetun source at
  `3d1e20c5551e9cae1f9d938dc7b7214a6987f27e`, the revision represented by the
  pinned v3.41.3 base. [`dependencies.patch`](dependencies.patch) updates the
  Go module graph; the compiler is Go 1.26.7. The candidate identifies itself
  as `v3.41.3-homelab.1`.
- [`native-inputs.json`](native-inputs.json) pins the base image, source
  archives, Alpine 3.22 SDK packages, and runtime libraries by SHA-256.
  OpenVPN 2.5 uses maintained revision
  `68e18e528197733663ab84fb3b70d7dba7732f24`. Its banner remains `2.5.11`;
  the full revision identifies the changes beyond that formal release.
  OpenVPN 2.6 uses the official 2.6.22 archive.
- [`native.Dockerfile`](native.Dockerfile) and
  [`native-build.sh`](native-build.sh) compile both `/usr/sbin/openvpn2.5`
  and `/usr/sbin/openvpn2.6` against musl and OpenSSL 3.5.8. APK installation
  runs without network access and requires signatures accepted by the pinned
  base's Alpine trust keys. Source archives have explicit checksum checks.
  Both builds preserve the Alpine configure options and use shared LZ4;
  `--enable-iproute2` keeps OpenVPN 2.6 DCO disabled.
- [`Dockerfile`](Dockerfile) adds the Go executable, both native executables,
  and only `libssl3`/`libcrypto3` 3.5.8-r0 from the APK inputs. It explicitly
  retains the installed versions of `iproute2-minimal`, `lzo`, `lz4-libs`, and
  `libcap-ng` before removing the stale OpenVPN package. Compiler, headers,
  and other SDK packages remain in the build stage.

## Validation

From a committed, clean repository checkout on native Linux/amd64, with Nix,
Docker/Buildx, and `/dev/net/tun` available:

```sh
nix develop --command python3 scripts/ci/gluetun-image-build.py
```

The [compatibility workflow](../../.github/workflows/gluetun-image.yml) runs
the same command. It requires selected upstream Go unit tests, two uncached
native builds with identical artifact bytes/modes, and two complete image
builds with matching config and manifest digests. Native build inputs and
build timestamps are fixed. The tested image must retain the base's runtime
configuration contract.

The [native fixtures](../../scripts/ci/gluetun-image-native.py) use owned
containers on an internal Docker network, synthetic keys, a private empty
Docker configuration, and the fixed local Docker socket. They check file
setting precedence and rejection, loopback-only pprof on/off behavior,
disconnected health, and firewall behavior. The firewall check verifies the
physical route, requires a fresh denied request, then restores that request
with a temporary rule limited to the owned peer and port. The rule is removed
after the control.

Each OpenVPN family must carry fresh HTTP in both directions through `tun0`
using AES-256-CBC/SHA256 static-key encryption, report the expected linked
OpenSSL, and fail a fresh request after its peer stops. These are isolated
packet compatibility tests; they do not establish provider connectivity or
a TLS handshake. Owned fixture resources and temporary data are cleaned up;
a cleanup error fails validation.

Trivy scans the complete candidate archive, requires an exact runtime APK
inventory and main Go binary coverage, checks expected dependency versions,
and rejects reported HIGH/CRITICAL findings. No detailed report is uploaded;
the private temporary report is discarded on success or failure. Database
updates can change scan results without changing image bytes.

## Native provenance and rollout gate

`/usr/share/homelab-gluetun/native/` records the input manifest, source and
binary checksums, compiler/package inventory, configure options, ELF library
dependencies, version output, and licenses. The stale OpenVPN APK record is
removed before installing the custom executables, which have no APK records.
APK inventory and scanner silence therefore do not establish coverage of the
rebuilt native code; review its source provenance and compatibility evidence
separately.

Registry publication and deployment require separate authorization. A later
review must select the registry, bind the published Linux/amd64 artifact to an
immutable digest, update the repository-owned Deluge pin, and pass real AirVPN
connection, health, traffic, fail-closed, and resource checks. Preserve the
previous pin and approve rollback through the same GitOps path. No storage or
namespace migration is part of this build.

See the [knowledge-base note](../../docs/knowledge-base/operations/gluetun-image-build.md)
and [Deluge runbook](../../clusters/homelab/apps/deluge/README.md).
