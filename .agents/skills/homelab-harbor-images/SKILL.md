---
name: homelab-harbor-images
description: Publish or verify homelab Harbor images and prepare image/chart updates that require mirrored digests. Use for image inventory, publication failures, or Talos mirror rollout; ordinary manifest edits do not require a registry migration.
---

# Homelab Harbor Images

Read [image delivery and coverage](../../../docs/harbor-image-mirroring.md).
For private custom builds, also read the workload's image runbook, such as
[NOFX private images](../../../docs/nofx-private-images.md).

## New image or chart version

1. Inventory declared, rendered and dynamically created images, including init
   containers and hooks. Use [the inventory helper](../../../scripts/harbor-image-inventory.py)
   and [coverage check](../../../scripts/ci/harbor-images-check.py); inspect their
   supported arguments before running. Resolve immutable manifest digests,
   retaining all required architectures.
2. Add public upstream artifacts to `scripts/config/harbor-images.json` in a
   prerequisite change. Keep upstream image provenance in workload manifests.
   The public `mirror` project must not receive private custom artifacts;
   those belong in `homelab` through their existing protected build workflow.
3. After protected merge, use the authorized `harbor-mirror.yml` dispatch with
   exact current `main` as `expected_sha`. Choose a scoped input only when the
   workflow and runbook explicitly support that scope.
4. Require successful digest/platform-preserving copies, aliases and fresh
   complete anonymous downloads. A manifest lookup, Harbor UI, successful build,
   or queued publication does not prove artifacts are available. Reuse an
   ancestor publication only under the runbook's exact bundle-equality rule.
5. Merge consuming image/chart changes only after publication evidence exists:
   Argo CD follows `main` immediately and strict mirrors reject missing content.
   Verify deployed digests and the original app action afterward.

For publication failures, preserve fail-closed missing-content detection in
[the publisher](../../../scripts/ci/harbor-publish.sh). Generic 404, auth,
transport, and hash mismatch errors do not mean an artifact is safely absent.
Reinspect the actual run before retrying; do not restart solely because a poll
timed out.

## Talos mirror changes only

Use [the repository operator helper](../../../scripts/talos-harbor-mirrors.py)
and the runbook's validated worker-first, control-plane-last sequence when the
user authorized node configuration rollout. Preserve the direct-upstream
bootstrap/rollback path. Verify registry configuration, node readiness and a
previously uncached pull with correlated Harbor requests. Cached success and
unchanged Pod image strings cannot prove live transport. Do not delete caches
or mutate Pods to manufacture that evidence.
