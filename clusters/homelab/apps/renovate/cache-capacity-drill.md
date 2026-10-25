# Dedicated Renovate cache capacity drill

`cache-capacity-drill-{base,fill,restore}.yaml` are staged outside
`kustomization.yaml`. The base contains the fixed script and NetworkPolicy;
each Job has its own selectable manifest. Both Job templates start suspended
and mount only `renovate-cache-dedicated`; neither has a GitHub credential or
Kubernetes API token. The shared `/homelab` export and old `renovate-cache`
claim are never drill targets.

## Prerequisites

1. Merge the reviewed dedicated-cache storage change, provision and verify the
   separate `10.1.0.2:/renovate-cache` QTS thick volume, and migrate the live
   CronJob to its static claim through GitOps. Confirm the old claim is retained.
2. Confirm Argo CD is Synced/Healthy at exact `main`; the live CronJob remains
   in full dry-run mode and mounts `renovate-cache-dedicated`. Verify the static
   PV and PVC are uniquely Bound to one another. Confirm no active Renovate Job.
3. Suspend the Renovate CronJob in a reviewed PR and wait for every old Job and
   Pod to finish. Add only `cache-capacity-drill-base.yaml` to Kustomization
   in another reviewed PR, and verify Argo CD remains Synced/Healthy. Keep both
   suspended Job manifests out: including either would mark the Renovate
   Application Suspended. Render and inspect the fixed claim, export guard,
   image, and selected Job before each activation.

## Fault and recovery

1. Add only `cache-capacity-drill-fill.yaml` to Kustomization and set its
   `suspend` to `false` in the same reviewed GitOps PR. Keep the restore Job
   omitted. The fill Job refuses any mount except NFSv3
   `10.1.0.2:/renovate-cache`, checks the real filesystem is 16–24 GiB, writes
   at most 24 GiB to its one named filler,
   and requires a failed 4 KiB probe. Verify the Job succeeded and record its
   UID. If it fails or times out, keep Renovate suspended and use the recovery
   Job; a partial filler is expected and safe to remove.
2. Unsuspend Renovate through a reviewed PR. The next scheduled dry-run Job
   must fail its 4 KiB cache probe before minting an App token. Record the Job
   and Pod UIDs, storage error, and failed-cycle alert without publishing raw
   private log lines. Suspend Renovate again and wait for all its Pods to stop.
3. Remove the fill Job from Kustomization and add only
   `cache-capacity-drill-restore.yaml` with `suspend: false` in the same
   reviewed PR. The restore Job removes only the named drill filler and any
   bounded partial drill probe, then requires a successful flushed 4 KiB write
   and at least 32 MiB free.
   Repeating the recovery Job is safe if the filler was already removed.
4. Remove the selected Job and base manifests from Kustomization through
   GitOps after recovery finishes. Resume the hourly dry-run CronJob through a
   reviewed PR. Verify the next scheduled Job succeeds and a later distinct
   Pod reuses the cache. Keep the old claim for rollback until the new volume's
   reuse is proven.

If the mount, volume size, or claim identity differs, stop. Do not fill
`/homelab`, delete the PVC, or clear Renovate's cache to complete this drill.
The missing/corrupt cache fixture and first real write-enabled proposal remain
separate acceptance gates.
