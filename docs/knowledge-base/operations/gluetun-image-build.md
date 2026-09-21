# Gluetun Image Build

Tags: #operations #validation #images

The [candidate build runbook](../../../images/gluetun/README.md) owns the
source, SDK, validation, and future rollout contract. The candidate is
inactive: the build workflow has no publishing step and Deluge's image pin
is unchanged. Native Linux CI must establish a successful complete build,
reproducibility, runtime compatibility, and image scan for the reviewed source.

The build keeps the pinned Gluetun application revision, updates its Go
toolchain/dependencies, and retains both OpenVPN binary paths. The maintained
2.5 source still reports `2.5.11`, so its full commit in
[`native-inputs.json`](../../../images/gluetun/native-inputs.json) is the
identity; 2.6 uses release 2.6.22. Signed offline Alpine SDK installation and
the two runtime OpenSSL packages keep build tools out of the resulting image.

The [input-availability review finding](https://github.com/Stuhlmuller/homelab/pull/991#discussion_r4059175597)
is a reliability follow-up: all 41 APK pins use Alpine's mutable `v3.22`
repository. The current gate checks repeated-build identity from exact inputs,
not permanent upstream availability. Every APK URL returned HTTP 200 on
2026-09-21; the Nix content-addressed mirror had none of those hashes. A removed
or changed upstream package fails the download/checksum gate and must not
trigger an automatic repin.

Next step for historical rebuilds: design a retained content-addressed APK
bundle using the existing GitHub Releases delivery surface, with an explicit
manual protected publication path bound to reviewed main and a clean,
unprivileged download/build that verifies every current SHA-256. Ordinary
Actions artifacts expire; Harbor and the backup S3 bucket are private and
cannot supply this unprivileged PR workflow without changing its trust model.
No publisher or archive is added by this candidate build PR. See the
[input availability contract](../../../images/gluetun/README.md#input-availability).

Required evidence includes repeated artifact/image identity, selected Go unit
tests, file setting and pprof controls, firewall denial with a scoped positive
control, and encrypted static-key traffic through both OpenVPN families.
These synthetic tests do not prove real AirVPN connectivity or TLS behavior.
Native provenance lives at `/usr/share/homelab-gluetun/native/`. The build
removes the stale OpenVPN APK record while retaining its required shared
dependencies at their installed versions. The custom executables have no APK
records, so exact runtime APK inventory and native source/compatibility
evidence are separate gates. No detailed scan report is uploaded; its private
temporary file is discarded on success or failure.

Publishing, a registry/digest selection, and an Argo CD rollout require
separate authorization plus real VPN acceptance and an approved previous-pin
rollback. This work changes no workload state, storage, or namespace contract.

Related: [[validation-gates]], [[../workloads/inventory]],
[[../workloads/application-notes#Gluetun candidate image]], and the
[Deluge runbook](../../../clusters/homelab/apps/deluge/README.md).
