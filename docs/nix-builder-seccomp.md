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
