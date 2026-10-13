# Nix builder seccomp profile

The bounded publication on 2026-10-12 failed at Nix's sandbox `pivot_root`
before either offline check completed. The original builder's live OCI
seccomp rules default to `SCMP_ACT_ERRNO` and omit `pivot_root`.
This is strong evidence of a seccomp boundary, not proof that no other
kernel restriction will prevent the next attempt.

The declared profile preserves every captured containerd 2.1.4 rule and
argument constraint for the existing amd64 builder capabilities, adding
only `pivot_root: SCMP_ACT_ALLOW`. It is a fixed profile, not a runtime
extension of RuntimeDefault: re-review it when Talos/containerd changes.
The added syscall allows changing the calling process's filesystem root.
Existing SYS_ADMIN and mount namespace isolation remain the trust boundary;
submit reviewed homelab source only.

## Protected delivery

Human approval must explicitly cover installing this profile on zimaboard-0
and zimaboard-1, selecting it only for the nix-builder container, and one
additional bounded publication attempt. Preparation alone is not approval.

1. Merge the profile, scoped operator helper, tests and this runbook through
   normal signed protected PR checks/review. Update affected OpenWiki pages
   through their native lifecycle in that PR.
2. From a clean checkout of exact current main, validate then execute the
   helper separately on each eligible worker after coordinator release:

   ```sh
   nix develop --command python3 -I scripts/talos-nix-builder-seccomp.py \
     --node 10.1.0.200 --talosconfig /path/to/private/talosconfig \
     --talosctl /path/to/talosctl-1.11.3
   # Only after explicit release: same command plus
   # --execute --expected-sha <full-current-main-sha>
   # Repeat separately for 10.1.0.201.
   ```

   The helper preserves active/persistent configuration and all unrelated
   profiles, refuses configuration/boot races, validates strictly for metal,
   applies only the named profile with no reboot, then waits up to 30 seconds
   for asynchronous exact profile readback (each read times out after 5 seconds;
   no second apply). No RuntimeDefault/global OCI setting is changed.
3. Only after both nodes contain the exact profile, merge the container-only
   Localhost selection and README through a second signed protected PR.
   Let Argo reconcile main; verify exact revision, Synced/Healthy/Succeeded,
   Pod 1/1, actual OCI profile, capabilities, sandbox=true,
   require-sigs=true and memory.max=1073741824.
4. After fresh four-node readiness/pressure/lease/metrics/headroom checks and
   coordinator release, run exactly one existing `scripts/nix-cache.py
   publish --linux` attempt. Keep the private key outside Git, record
   Pod UID/attempt UUID/session, retain deadlines and owned cleanup, and
   never restart after an observation timeout. Any terminal failure consumes
   that authorization; report it without widening the profile or retrying.
5. Completion requires both actual signed outputs and fresh CI substitution
   without check rebuild, plus fresh live plans/cluster checks.

## Rollback

First revert the builder container to RuntimeDefault through a protected PR
and natural Argo reconciliation. Once no Pod selects this profile, use the
same scoped helper with `--rollback`, first validate, then explicitly released
`--execute --expected-sha <full-current-main-sha>` on each worker. The helper
refuses profile removal while any existing Pod selects it, preserves other
profiles, and requires an actual file-not-found readback before reporting
success, including an already absent config entry. Transport/authentication
failures never prove file absence. Retain historical
failure evidence. Sandbox, signature checks and the 1GiB limit never change.

## Talos 1.11.3 materialized path

The pinned Talos `SeccompProfilesDirectory` constant is
`/var/lib/kubelet/seccomp/profiles`; the Kubernetes Localhost reference remains
`profiles/nix-builder-containerd-2.1.4.json` relative to kubelet's seccomp root.
On 2026-10-13 UTC, the first released worker-0 helper installed the approved
profile but exited at readback because it checked the legacy
`/var/lib/seccomp/profiles` path. Read-only inspection found the exact reviewed
profile at the pinned kubelet path; the original builder remained RuntimeDefault
with zero restarts. Stop-on-failure held worker-1 installation and all builder
selection/publication. Correct only verification and rollback readback paths
through a protected PR before any renewed scoped installation release. No
additional apply, reboot, resource change or publication followed this failure.

After the protected readback repair merged as `02efe9cb`, worker 0 was verified
read-only with no second apply; worker 1's first released helper completed with
exit 0. Independent readback found matching active/persistent configurations,
unchanged boots and the same approved materialized profile on both workers:
canonical SHA256 `aa9efdab8100bee9695b8c72c107ddf338a740cff4190e0611893c31d455b760`.
All four nodes remained Ready without pressure. The original builder remained
RuntimeDefault with zero restarts at this receipt; container selection requires
the separate protected runtime PR and Argo rollout. No publication retry ran.

## Verified rollout; publication headroom hold

Protected runtime PR #1301 merged as `6dd7b02c`. Natural Argo reconciliation
reached that exact revision with Synced/Healthy/Succeeded and one Ready builder
with zero restarts. Independent running-OCI readback matched the reviewed
profile hash above. The effective/bounding capabilities retained NET_ADMIN,
seccomp filtering was active, Nix reported sandbox=true and require-sigs=true
with nixbld users, and the actual cgroup memory.max was 1073741824 bytes.
Baseline memory peak was 24256512 bytes with zero max/OOM/OOM-kill events.
These observations prove profile delivery, not successful sandbox builds.

At 2026-10-13 05:09 UTC, fresh metrics showed 1243.4 MiB measured headroom
on the selected worker and 978.4 MiB on the other eligible worker. All four
nodes were Ready without pressure/network unavailability, with fresh leases;
the repository preflight nevertheless rejected publication because the selected
worker was below its required 1536 MiB headroom. No publication command or
build attempt started at that receipt; the single newly authorized retry was
still unused. No signed outputs or warm-CI substitution had been established.

Keep the 1GiB limit and existing preflight threshold. Resume only after natural
headroom recovery passes fresh full preflight and the separate coordinator
publication release, or after a separately reviewed and explicitly approved
capacity change. Do not restart Pods, reclaim host caches, move the workload,
change other workloads, or lower the guard to manufacture acceptance. Keep
actual publication, fresh signed substitutions and live checks as separate
completion gates. This receipt is dated evidence; recheck live metrics.


## Signed publication and warm CI receipt

On 2026-10-13, natural selected-worker headroom reached 1589.9 MiB against the
unchanged 1536 MiB guard. Fresh full preflight and exact source, Argo, original
Pod UID, running OCI profile and runtime settings passed. After the separate
coordinator release, immediate preflight passed and the one bounded publication
attempt completed with exit 0 on main
`6dd7b02ce43cefad2b62bc9ab2964b40c4b15dce`. The retry is consumed; this receipt
releases no additional attempt. Sandboxing, signature checks and the 1GiB limit
remained enabled. Both Linux checks completed and were signed and published:

- `/nix/store/d2dgkznjybvd1n3y154pp25nxnbp4h5n-homelab-offline-tests`
- `/nix/store/kwbm00csjqhcihb0kqlsgd0dzsqj8n5l-homelab-manifest-policy`

Independent copies from the [published cache](https://github.com/Stuhlmuller/homelab/releases/tag/nix-cache)
into fresh disposable stores accepted both outputs with the committed public
key. Unknown-key and unsigned variants were rejected specifically by signature
validation. The original Pod's owner lock and workspace were absent afterward,
with no Nix/timeout process remaining. Peak memory was 948531200 bytes (905 MiB),
with zero max/OOM/OOM-kill events; all four nodes remained Ready without pressure.

The narrowly rerun [main validation job](https://github.com/Stuhlmuller/homelab/actions/runs/38349343865/job/115167993774)
(attempt 2, exact `6dd7b02c`) finished successfully. Its 06:49:28 UTC log copied
both exact outputs from the committed GitHub release URL without rebuilding
either check. The protected-main trust policy and unchanged sandbox/signature
wrapper were used; remaining validation ran fresh. This establishes cache
acceptance for that exact source tree, not later fingerprints. Merging these
docs changes the broad check inputs. Fresh live plans remain a separate,
uncompleted gate; this receipt authorizes no credential, capacity or workload
change and no migration plan/apply.
