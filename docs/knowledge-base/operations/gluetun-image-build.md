# Gluetun Image Build

Tags: #operations #validation #images

The [candidate build runbook](../../../images/gluetun/README.md) owns the
source, SDK, validation, and future rollout contract. The candidate is
inactive: the build workflow has no publishing step and Deluge's image pin
is unchanged. Native Linux CI has not yet established a successful complete
build, reproducibility, or runtime compatibility.

The build keeps the pinned Gluetun application revision, updates its Go
toolchain/dependencies, and retains both OpenVPN binary paths. The maintained
2.5 source still reports `2.5.11`, so its full commit in
[`native-inputs.json`](../../../images/gluetun/native-inputs.json) is the
identity; 2.6 uses release 2.6.22. Signed offline Alpine SDK installation and
the two runtime OpenSSL packages keep build tools out of the resulting image.

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
