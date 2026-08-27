<!-- markdownlint-disable MD013 -->

# Radarr

Radarr uses the shared `media-postgres` PostgreSQL 14 instance for its
application and log databases. This app follows the Servarr PostgreSQL runbook:
`radarr-main` and `radarr-log` must exist before Radarr starts, and Radarr is
configured through `/config/config.xml` fields rather than an application
environment-variable override.

## PostgreSQL Configuration

The `configure-postgres` init container reads the `RADARR_POSTGRES_*` keys from
`media-postgres-arr-env`, then sets these `config.xml` entries on the
persistent `/config` volume:

```xml
<PostgresUser>media_apps</PostgresUser>
<PostgresPassword>runtime-secret-from-aws-ssm</PostgresPassword>
<PostgresPort>5432</PostgresPort>
<PostgresHost>media-postgres.media.svc.cluster.local</PostgresHost>
<PostgresMainDb>radarr-main</PostgresMainDb>
<PostgresLogDb>radarr-log</PostgresLogDb>
```

The database password comes from AWS SSM Parameter Store through External
Secrets. Do not commit it to this repository.

## Authentication

The startup `configure-postgres` init container also sets
`<AuthenticationMethod>External</AuthenticationMethod>` and
`<AuthenticationRequired>DisabledForLocalAddresses</AuthenticationRequired>` in
`/config/config.xml`. The init container removes stale
`AuthenticationEnabled` and `AuthenticationType` entries first, then rewrites
the target tags so exactly one copy remains. This matters because old
`AuthenticationEnabled=true` config forces Forms authentication before Radarr
reads `AuthenticationMethod`, and duplicate XML tags are treated by Radarr as
missing values.

The Radarr app container also sets `RADARR__AUTH__METHOD=External` and
`RADARR__AUTH__REQUIRED=DisabledForLocalAddresses` as a secondary runtime guard.
Radarr targets Octelium as the external access boundary. The stable
`https://radarr.stinkyboi.com` hostname resolves to the Octelium service
address, Funnel stays disabled, and Radarr's own password prompt is
intentionally disabled.

This avoids recurring lockouts when the internal Radarr username/password state
drifts or is reset during config/database migrations. If Radarr is ever exposed
outside Octelium or another reviewed private access layer, restore Forms
authentication or add a dedicated forward auth layer before rollout. Upstream
documents `External` as the config-file-only mode for deployments protected by
external authentication:
<https://wiki.servarr.com/radarr/faq#authentication-method>.

The app has startup, readiness, and liveness probes against
`/initialize.json`. That endpoint is the UI bootstrap path and includes the
runtime API key in its response body, so validation commands must discard the
body:

```sh
kubectl -n media exec deploy/radarr -c app -- \
  sh -c 'curl -fsS -o /dev/null http://127.0.0.1:7878/initialize.json'
kubectl -n media exec deploy/radarr -c app -- \
  sh -c 'grep -nE "<Authentication(Enabled|Method|Required|Type)>" /config/config.xml || true'
```

Expected config output contains only one `AuthenticationMethod=External` line
and one `AuthenticationRequired=DisabledForLocalAddresses` line. Do not print
`/initialize.json`; it contains the live Radarr API key.

## Config Recovery And Local Storage

Active config lives on the retained `radarr-config-local` volume backed by
`/var/lib/radarr` on `zimaboard-0`. The old `radarr-config` NFS claim stays
declared as the archive and rollback target, but the app Pod no longer mounts
it. Radarr uses a `Recreate` rollout to protect its singleton local state.

The completed one-time migration copied and validated the legacy config tree,
recovered a valid backup when needed, and wrote
`.nfs-migration-complete`. Its init container, script ConfigMap, and read-only
NFS mount are removed from steady state; `configure-postgres` now follows
`prepare-config` directly.

`radarr-config-backup` writes a verified compressed archive of local config
back to the retained NFS claim at 04:00 Pacific and keeps 14 days. This is a
best-effort snapshot of a running app, so retain several generations. It is the
only steady-state Radarr workload that mounts the old config claim. The app Pod
does not need QNAP config availability to start.

The local volume survives ordinary Talos reboots and upgrades because `/var` is
on the Talos `EPHEMERAL` system volume. It remains tied to `zimaboard-0` and is
lost if that system disk is reset or fails. The 10 Gi PV capacity is descriptive
for `hostPath`, not an enforced quota. Move it to a dedicated Talos UserVolume
if that recovery model becomes unacceptable.

Validate steady state without printing secret config values:

```sh
kubectl get persistentvolume radarr-config-local
kubectl -n media get pvc radarr-config-local radarr-config
kubectl -n media get pod -l app.kubernetes.io/name=radarr -o wide
kubectl -n media exec deploy/radarr -c app -- \
  test -f /config/.nfs-migration-complete
kubectl -n media exec deploy/radarr -c app -- \
  sh -c 'test -s /config/config.xml && test "$(grep -c "<ApiKey>[^<][^<]*</ApiKey>" /config/config.xml)" -eq 1'
kubectl -n media exec deploy/radarr -c app -- \
  sh -c 'curl -fsS -o /dev/null http://127.0.0.1:7878/initialize.json'
kubectl -n media get cronjob radarr-config-backup
```

Require both claims to remain bound, the pod to be ready on `zimaboard-0`, the
marker and non-empty API key guard to pass, and Radarr searches plus Prowlarr
integration to work. Verify the latest CronJob timestamp and archive validation
log:

```sh
kubectl -n media get cronjob radarr-config-backup \
  -o jsonpath='{.status.lastSuccessfulTime}{"\n"}'
kubectl -n media get job \
  -l app.kubernetes.io/name=radarr-config-backup
kubectl -n media logs job/<latest-radarr-config-backup-job>
```

The one-time source copy is complete; do not point Radarr back at the stale NFS
root. Rollback requires a reviewed revision that stops Radarr, restores one
selected and validated archive into `radarr-config-local` with UID/GID `1000`,
and removes the restore Job before starting Radarr. Preserve both claims
throughout recovery.

## Media Storage

Radarr mounts the static `media-movies` PVC at `/movies` and the shared
`media-downloads` PVC at `/downloads`. Both claims point at the QNAP `/media`
NFS export instead of the default `/homelab` provisioner path.

The `media-movies-migration` Job copies files from the older `radarr-media` PVC
into `/media/movies`, sets write-friendly NFS permissions, and verifies that the
target path can be written before the app switches to the new claim. The older
`radarr-media` claim remains in desired state as the migration source and
rollback reference until the copy is verified.

## Migration Notes

The Servarr guide requires Radarr `v4.1.0.6133` or newer. The Git baseline pins
the `lscr.io/linuxserver/radarr` `6.3.0` release with a digest, which satisfies
that version floor while keeping the deployed image immutable and reviewable.

Radarr does not create its PostgreSQL databases and does not back them up. The
`media-postgres` init script creates `radarr-main` and `radarr-log`; backup and
restore coverage is tracked in `docs/storage-nfs.md`.

This deployment configures Radarr to use PostgreSQL but does not migrate
existing SQLite data from `/config/radarr.db`. To preserve existing data,
follow the upstream migration guide before treating the rollout as complete:

<https://wiki.servarr.com/radarr/postgres-setup>
