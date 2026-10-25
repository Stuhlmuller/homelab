# Dedicated Renovate package-cache corruption drill

`cache-corruption-drill.yaml` is staged outside the Renovate Kustomization. It
contains one suspended Job, its fixed script, and a deny-all NetworkPolicy.
The Job mounts only `renovate-cache-dedicated`, the script ConfigMap, and an
ephemeral `/tmp`. It has
no GitHub App Secret, Kubernetes API token, or network access. Its only cache
mutation replaces the existing public `chainguard-actions/actions-checkout`
GitHub-tags entry with malformed bytes; private cache entries are not read or
logged. Renovate 44.167.4 treats that entry as a miss, refetches it, and writes
a new package entry even in full dry-run mode. Repository-cache saves are
suppressed in full dry-run mode and cannot prove this recovery path.

## Preconditions

1. Finish the dedicated PVC cutover. Verify Argo CD is Synced/Healthy at exact
   `main`; the hourly CronJob is in full dry-run mode and mounts
   `renovate-cache-dedicated`. Verify the static PV/PVC binding and the QTS
   export before changing cache contents.
2. Confirm the public `chainguard-actions/actions-checkout` dependency is still
   extracted from `.github/workflows/` and has an existing warm package-cache
   entry. The injector checks the exact key and requires more than two hours
   of native expiry remaining; if it fails, stop. Wait for a later healthy scan
   or select another proven public key through a reviewed source change. Do not
   inspect or print cache
   payloads or substitute a private package.
3. Suspend the Renovate CronJob through a reviewed GitOps PR and wait for every
   Renovate Job and Pod to finish. Ensure the next scheduled scan will begin
   more than 15 minutes after the last successful scan: Renovate's outer
   `datasource-releases-github-tags` cache has a 15-minute TTL and could
   otherwise bypass the deliberately malformed inner entry.

## Fault and recovery

1. In a separate reviewed PR, add only `cache-corruption-drill.yaml` to the
   Renovate Kustomization and set its Job `suspend: false` in the same change.
   Render and inspect the fixed image, claim, mount/export guard, public key,
   credential absence, and deny-all policy. Update the staged-phase assertions
   in `scripts/ci/renovate-cache-corruption-drill-test.mjs` and
   `scripts/ci/renovate-cache-capacity-drill-test.py` to the activation phase;
   their staged absence assertions intentionally fail after activation.
   Require the injector Job to succeed and record its UID. A missing/expired
   key, wrong export, wrong volume size, or unexpected image version fails
   before `cacache.put` writes anything.
2. Remove the Job, ConfigMap, and NetworkPolicy from Kustomization and resume
   the hourly full dry-run CronJob through another reviewed PR. Update the
   phase assertions again. The next scheduled Pod must process every eligible
   repository and refetch the public action tag after the malformed-entry
   read. Use only restricted, scoped TRACE/DEBUG logs to verify the exact
   public key's read failure and subsequent save. Record the Job/Pod UIDs,
   aggregate repository outcomes, and no GitHub writes; do not publish raw
   logs or private keys/packages.
3. A later scheduled Pod with a distinct UID must show a hit for that exact
   key without a repeated corruption error. Record only the public key,
   timestamps, UIDs, and aggregate results in the receipt. If the next scan
   cannot refetch, keep the runner in dry-run mode and repair through reviewed
   desired state. Do not reset the PVC or edit NFS files by hand.

The injector fails closed if the public key is not already warm. A successful
injector Job alone does not complete T042; both later scheduled-run outcomes
are required. The missing-cache and full-volume drills have separate receipts.
