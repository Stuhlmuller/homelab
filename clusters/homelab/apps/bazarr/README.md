# Bazarr

Bazarr manages English subtitle sidecars for the existing Sonarr and Radarr
libraries. Its single replica runs in `media` on `zimaboard-0`, using the same
`/tv` and `/movies` roots as those applications. No path mapping is needed.

## Subtitle policy

The `English captions` profile accepts regular or SDH English subtitles without
preferring SDH and excludes forced-only subtitles. Embedded English tracks also
satisfy the requirement. The PostSync hook creates the profile, makes it the
default for new series and movies, enables integrations, and schedules both
library imports. It returns without waiting for library scans or providers.
Existing operator profiles remain intact.

Run `finish-setup` after deployment to wait for imports, assign the profile to
items without an existing profile, and verify the initial missing-subtitle
searches. It records completion only after both searches finish successfully;
rerun after failure, timeout, or a committed profile change. Normal pod restarts
preserve this marker. Sonarr's initial import can also queue episode searches;
the explicit setup search covers movies and any remaining episodes. Bazarr
repeats TV and movie wanted searches every six hours. Free providers are declared
in `bootstrap.py`; provider availability still requires live acceptance.

## State and credentials

- SQLite and app config stay on the retained 5 Gi `bazarr-config-local` volume
  at `/var/lib/bazarr` on `zimaboard-0`. Recreate ordering prevents concurrent
  database writers.
- The retained 5 Gi `bazarr-config-backups` NFS claim holds nightly archives.
  `bazarr-config-backup` runs at 04:45 America/Los_Angeles with 14-day retention.
  It snapshots SQLite using the online backup API, runs `PRAGMA integrity_check`,
  and verifies the archive contains the database and config before publishing it.
  Media captions live beside the source files and need NAS media backup coverage
  separately. The `bazarr-initial-backup` PostSync hook runs the same verified
  backup after profile/default configuration, establishing the first archive
  during rollout. Library imports may still be running; scheduled backups also
  capture their later state and the completed setup marker.
- Initialization reads the existing Sonarr/Radarr API keys through read-only
  mounts of their local config claims. The main Bazarr container cannot access
  either source config claim. Keys remain in private runtime config and backups.
- Sonarr owns `media-tv`; Radarr owns `media-movies`. Bazarr only consumes them.
  Removing Bazarr must preserve these shared library claims and subtitle files.

## Private access

Connect the authenticated Octelium desktop/CLI client, then open
[http://bazarr](http://bazarr). This uses the private `bazarr.default` WEB Service
and existing `homelab-human-web-access` policy. It has no public DNS record,
Cloudflare Tunnel route, or anonymous access. Short service hostnames are part of
[Octelium client access](https://octelium.com/docs/octelium/latest/user/cli/access).

The Kubernetes operator fallback is:

```sh
kubectl -n media port-forward service/bazarr 6767:6767
```

Then open [http://127.0.0.1:6767](http://127.0.0.1:6767). The port-forward defaults
to loopback; keep that default.

## Deployment and acceptance

1. Run repository static/security gates, render the app-template chart at the
   version declared in `IaC/stacks/bazarr/stack.hcl`, and validate the Kustomize
   overlay. Merge through the protected PR workflow.
2. Dispatch `harbor-mirror.yml` on current `main` with its exact SHA as
   `expected_sha` and `image_scope=bazarr`. Require successful publication and
   verification before applying Bazarr. Talos registry mirrors use
   `skipFallback: true`, so the new digest-pinned GHCR Bazarr image must already
   exist in Harbor. The fixed Bazarr scope copies only its app and BusyBox init
   images, verifies digest identity and complete anonymous pulls, and excludes
   unrelated historical images.
3. Dispatch `terragrunt-apply.yml` on current `main` with its exact SHA and
   `argocd_app=bazarr`. The generated unit depends on `platform-storage`,
   `radarr`, and `sonarr`. Those dependencies order registration, so separately
   verify their runtime health and bound claims.
4. Require the Bazarr Application to become `Synced`/`Healthy`, the pod to be
   ready, and the profile/default configuration hook to succeed.
5. From a clean checkout at the reviewed current `main` SHA, reconcile the
   private native Octelium Service. Preview first:

   ```sh
   python3 -I scripts/octelium-bazarr-reconcile.py
   python3 -I scripts/octelium-bazarr-reconcile.py \
     --execute --expected-sha <full-reviewed-main-sha>
   ```

   The helper uses the existing operator login and pinned native transport,
   applies only `bazarr.default`, checks its private human-access contract, and
   requires a second apply with no changes. It never prunes the catalog.
6. Complete application setup outside Argo's sync timeout:

   ```sh
   kubectl -n media exec deployment/bazarr -c app -- \
     /lsiopy/bin/python3 /bootstrap/bootstrap.py finish-setup --timeout 1800
   ```

   This repository-owned command waits for Arr library coverage and active
   import jobs, assigns only missing profiles, then requires both initial search
   jobs to complete. The timeout covers import and search waiting; individual
   API calls have a 90-second network timeout. A failure leaves the completion
   marker unset; inspect the private job/provider status and rerun. Increase
   `--timeout` for a larger library without extending the Argo operation.
   Verify the English profile also applies to newly imported series/movies.
   Confirm at least one real English sidecar next to an episode or movie, then
   confirm Bazarr marks that language as downloaded. Existing embedded subtitles
   can satisfy an item's requirement; choose an item actually missing English.
7. Verify the private UI through Octelium and the successful
   `bazarr-initial-backup` hook with its verified archive on the backup claim.
   Then verify the first scheduled `bazarr-config-backup` run. A healthy pod
   alone does not establish subtitle or backup acceptance.

Provider availability and subtitle matches vary by release. A missing result
must remain visible as wanted content, not be recorded as a successful download.
Do not configure paid providers or create provider accounts implicitly.

## NAS media access

The [NFS storage contract](../../../../docs/storage-nfs.md) maps every client
UID to the NAS guest identity. Owner-1000 directories with mode `0770` can
therefore hide registered content from both Sonarr and Bazarr. Changing the
container UID or supplemental groups does not repair this server-side boundary.

The fixed-scope operator helper inventories only registered Sonarr and Radarr
library paths. Preview from the repository; output contains counts only:

```sh
python3 -I scripts/nas-media-permissions.py
```

After reviewing and merging the helper, execute from a clean checkout matching
current `main`. Choose a new private journal path outside the repository:

```sh
python3 -I scripts/nas-media-permissions.py \
  --execute --expected-sha <full-reviewed-main-sha> \
  --journal /private/operator-backups/media-modes.json --rescan
```

The helper uses the existing `themanofrod@10.1.0.2` SSH account, verifies UID
1000, and writes the original modes, device/inode identities, and private paths
to an exclusive mode-0600 journal before changing anything. It applies `a+rwX`
only to owner-1000 directories and `a+r` only to owner-1000 files beneath those
registered roots. Existing guest-owned objects, unrelated NAS folders, file
contents, symlinks, and other mounted filesystems remain outside its scope.
The explicit `/share/media` share alias is resolved once; symlinks beneath it
are rejected at registered roots and before each permission change. Do not run
while moving or replacing library directories.

`--rescan` optionally queues scans for the registered Arr items after permission
verification, making previously hidden files eligible for Bazarr synchronization.
Execution requires both the exact reviewed SHA and the private journal; preview
does not change NAS state or queue scans. A failed or interrupted execution can
leave partial permission changes, so retain its journal and inspect before retry.

For rollback, use the journal's original modes in a reviewed owner-side repair:
first stop caption writes, confirm each object's UID, device, and inode still
match, then restore only those recorded modes. Never restore onto replaced files.
The journal contains private library names and must never be committed.

## Recovery and rollback

Pause the Bazarr writer through a reviewed GitOps change before restoring its
local config/database state from a verified backup. Retain the previous local
state until the restored app passes library and subtitle checks. Restore lost
sidecar captions from the NAS media backup independently of Bazarr config.

To stop subtitle automation, set the controller replica count to zero in git
and let Argo CD reconcile it. To roll back an image, revert the digest pin only
when its database schema is compatible; otherwise restore the matching verified
backup with the writer stopped. Preserve the config, backup, and shared media
claims. Local config depends on `zimaboard-0`; an NFS archive shares the QNAP
failure domain and is not an off-site copy.
