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

The pinned Supervisor creates UID/GID 543210 and allocates 65536 subordinate IDs
starting at 543211 (ending at 608746). Kubernetes defaults to only 65536 IDs per
Pod, which cannot represent that range. Both Cordium Talos patches therefore set
`machine.kubelet.extraConfig.userNamespaces.idsPerPod: 1048576`. Kubernetes 1.34
[supports this setting](https://v1-34.docs.kubernetes.io/docs/concepts/workloads/pods/user-namespaces/#id-count-for-each-of-pods).
Apply and verify this configuration on every eligible node before rolling out
`hostUsers: false`; changing the sysctl alone is insufficient. Existing running
Pods keep their mappings. Requiring a larger ID range preserves the Supervisor's
UID and existing volume ownership; do not renumber users or chown original PVCs.

## Protected publication

After source merge and successful Linux build validation, dispatch
`cordium-nocturne-publish.yml` with `expected_sha` equal to exact current `main`.
The workflow builds before receiving credentials and rechecks main before the
existing production credential lane. `publish-cordium-nocturne` accepts only that
workflow on main and publishes only
`harbor.stinkyboi.com/homelab/homelab-cordium-nocturne:homelab-<SHA>`.
It verifies a complete authenticated pull, signs inside the cluster, verifies the
enrolled public-key fingerprint/signature, and emits the validated immutable
reference as a public artifact. No private signing key is exported to CI.

Keep the consuming Deployment change separate until that artifact exists.
A successful diagnostic build alone is not a publication or runtime acceptance.
This publication uses the existing Octelium CI transport until its replacement
passes its own acceptance gates. It neither retires routes nor changes credentials.

The excluded `octelium/cordium-nocturne-pull` ExternalSecret renders a Docker-config
Secret from `/homelab/cordium/nocturne-harbor-pull-password`, a declared generated
copy of the existing `/homelab/harbor/robot-pull-password` (`robot$homelab+pull`).
The namespace-specific alias preserves the approved application-prefix policy.
Its exact-parameter reader grant and generated copy require a reviewed private
saved plan/apply and metadata verification before adding this manifest to the
Cordium kustomization. It is currently excluded to avoid a missing-parameter
ExternalSecret rollout. No password value or rotation is supplied by an operator.

The future consuming Pod references the Secret through `imagePullSecrets`;
never mount it or expose it as an application env var. The contract uses OnChange
revision v1: after an approved producer rotation, reconcile the generated copy,
advance its revision, wait for readiness, and verify a fresh image pull. Secret
materialization alone activates no controller image or runner pool.
