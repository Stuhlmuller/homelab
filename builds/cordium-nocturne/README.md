# Cordium workspace reservations

The pinned v0.12.7 Nocturne generator requests 5 MiB and 10 millicores for
workspaces whose configured limits may be 2 GiB and 2 CPUs. The
[bounded smoke receipt](../../docs/evidence/cordium-startup-capacity-2026-10-17.json)
records this mismatch, a contemporaneous worker runtime failure, and verified
cleanup. The nested image-pull stall's exact cause remains unproven.

`build.sh` uses checksum-pinned upstream source and its Go 1.25.8 Linux toolchain.
It runs the real Pod-spec generator with default and explicit limits and
requires the under-reservation assertion to fail, applies the reservation/user-namespace
patch, then requires the same test to pass. Compilation failure does not count as
reproducing the defect. It then compiles the Linux Nocturne binary, replaces it in the digest-pinned
upstream runtime image and runs a non-root/read-only/offline startup smoke that must reach the missing-cluster
configuration guard. It creates
no workspace or cluster resources and publishes no image.
The hosted diagnostic job is temporary bootstrap infrastructure; include it in
the full Cordium selector cutover after the fleet passes live acceptance.

```sh
# Linux x86_64, with curl, jq, sha256sum, tar, patch and Docker
bash builds/cordium-nocturne/build.sh
```

Acer eligibility also needs user-namespace prerequisites, storage topology and
node-path coverage, enough CPU/memory/Pod overhead, and a declared controller
image rollout. Adding a node label alone is insufficient. Preserve existing
worker eligibility and bound PV node affinity for the six stopped workspaces.
Do not change runtime placement or raise startup deadlines to claim this test
fixes the live startup failure.

The source fix makes CPU/memory requests equal to the configured limits and sets
`hostUsers: false`. Tests exercise every production file in the generator package;
unrelated Linux process/integration tests are excluded. The real generator test
failed before the patch and passed after it with Go 1.25.8 on macOS; Linux CI is
separate. This patch is not a deployed controller image.

Acer storage support is prepared while `zimaboard-1` paths/topology remain intact.
The user-namespace DaemonSet follows the declared Cordium role. Acer has **not**
been assigned that role, so these prerequisites do not enable CI there. Its
control-plane Talos sysctl patch is staged for the guarded config path. The live
StorageClass accepted the expanded topology in server-side dry run; no replacement
or PV/PVC mutation occurred. Add eligibility only after image/isolation acceptance
and at least 2 GiB plus Pod overhead is schedulable. Current Acer reservations are
still too high. Roll back prerequisites by restoring the old source; never delete
or rewrite existing bound local PV node affinity.

The control-plane sysctl patch validates against a freshly generated Talos 1.11.3
teaching configuration; this is schema validation, not validation of Acer's private
current configuration. Before an eventual apply, render that private current
configuration through the guarded [control-plane workflow](../../docs/talos-control-plane-maintenance.md),
adding `--patch @.talos/patches/controlplane-cordium-user-namespaces.yaml`, validate
with `talosctl validate --mode metal --strict`, and review its dry-run diff.
Never apply the teaching configuration.
