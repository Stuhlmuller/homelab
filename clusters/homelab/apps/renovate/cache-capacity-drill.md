# Dedicated Renovate cache capacity drill

`cache-capacity-drill.yaml` is staged outside `kustomization.yaml`. Its two
Jobs start suspended and mount only `renovate-cache-dedicated`; neither has a
GitHub credential or Kubernetes API token. The shared `/homelab` export and
the old `renovate-cache` claim are never drill targets.

## Prerequisites

1. Merge the reviewed dedicated-cache storage change, provision and verify the
   separate `10.1.0.2:/renovate-cache` QTS thick volume, and migrate the live
   CronJob to its static claim through GitOps. Confirm the old claim is retained.
2. Confirm Argo CD is Synced/Healthy at exact `main`; the live CronJob remains
   in full dry-run mode and mounts `renovate-cache-dedicated`. Verify the static
   PV and PVC are uniquely Bound to one another. Confirm no active Renovate Job.
3. Suspend the Renovate CronJob in a reviewed PR and wait for every old Job and
   Pod to finish. Add `cache-capacity-drill.yaml` to Kustomization in another
   reviewed PR with both Jobs still suspended. Render and inspect the exact
   fixed claim, export guard, image, and suspended state before reconciliation.

## Fault and recovery

1. Unsuspend only `renovate-cache-capacity-fill` through a reviewed GitOps PR.
   It refuses any mount except NFSv3 `10.1.0.2:/renovate-cache`, checks the real
   filesystem is 16–24 GiB, writes at most 24 GiB to its one named filler,
   and requires a failed 4 KiB probe. Verify the Job succeeded and record its
   UID. If it fails or times out, keep Renovate suspended and use the recovery
   Job; a partial filler is expected and safe to remove.
2. Unsuspend Renovate through a reviewed PR. The next scheduled dry-run Job
   must fail its 4 KiB cache probe before minting an App token. Record the Job
   and Pod UIDs, storage error, and failed-cycle alert without publishing raw
   private log lines. Suspend Renovate again and wait for all its Pods to stop.
3. Unsuspend only `renovate-cache-capacity-restore` through a reviewed PR. It
   removes only the named drill filler and any bounded partial drill probe,
   then requires a successful flushed 4 KiB write and at least 32 MiB free.
   Repeating the recovery Job is safe if the filler was already removed.
4. Remove the drill manifest from Kustomization through GitOps after the Jobs
   finish. Resume the hourly dry-run CronJob through a reviewed PR. Verify the
   next scheduled Job succeeds and a later distinct Pod reuses the cache. Keep
   the old claim for rollback until the new volume's reuse is proven.

If the mount, volume size, or claim identity differs, stop. Do not fill
`/homelab`, delete the PVC, or clear Renovate's cache to complete this drill.
The missing/corrupt cache fixture and first real write-enabled proposal remain
separate acceptance gates.
