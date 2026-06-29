# Media PostgreSQL

`media-postgres` is the shared PostgreSQL 14 instance for Sonarr, Radarr, and
Prowlarr. It runs in the `media` namespace, persists data on the `nfs-default`
StorageClass, and exposes only the in-cluster Service
`media-postgres.media.svc.cluster.local:5432`.

## Secret Contract

The database password lives in AWS SSM Parameter Store at
`/homelab/media-postgres/app-password`. The `media-postgres-auth`
ExternalSecret creates the credentials consumed by the StatefulSet, and the
`media-postgres-arr-env` ExternalSecret creates the PostgreSQL settings used by
the `configure-postgres` init containers for Sonarr, Radarr, and Prowlarr.
Dispatcharr uses a dedicated PostgreSQL 17 StatefulSet in the Dispatcharr app
overlay because upstream modular mode expects PostgreSQL 17-compatible storage.

Terragrunt generates this value and writes it to SSM. The pod includes a
`require-real-password` init container that fails when `POSTGRES_PASSWORD` is
empty or still set to `REPLACE_ME`, which catches incomplete bootstrap runs.

The Docker official PostgreSQL image creates `POSTGRES_USER` as a superuser on
first initialization. This is intentional here because the Servarr Prowlarr
PostgreSQL guide states that Prowlarr housekeeping needs a superuser for vacuum
work. Revisit this before adding unrelated apps to this database instance.

`PGDATA` points at a `pgdata` subdirectory inside the PVC. The pod runs as
UID/GID 65534 because the QNAP NFS export squashes writes to its anonymous user
and denies `chown`; PostgreSQL requires the server process to own the data
directory.

## Databases

The init script creates the logical databases that Servarr expects:

| App | Main database | Log database |
| --- | --- | --- |
| Sonarr | `sonarr-main` | `sonarr-log` |
| Radarr | `radarr-main` | `radarr-log` |
| Prowlarr | `prowlarr-main` | `prowlarr-log` |
The init script runs only when PostgreSQL initializes an empty data directory.
Changing database names after first boot requires an explicit migration plan.

Sonarr, Radarr, and Prowlarr follow the official Servarr PostgreSQL runbooks by
using PostgreSQL 14, pre-created main and log databases, and persistent
`config.xml` entries for `PostgresUser`, `PostgresPassword`, `PostgresPort`,
`PostgresHost`, `PostgresMainDb`, and `PostgresLogDb`.

## Existing SQLite Data

This desired state points the apps at PostgreSQL. It does not migrate existing
SQLite data from the `/config` PVCs. To preserve existing Sonarr, Radarr, or
Prowlarr data, take app backups first and follow the Servarr PostgreSQL
migration runbooks before treating the rollout as complete. A fresh rollout
without migration will start each app against empty PostgreSQL databases while
leaving the old SQLite files on the config PVCs.

Upstream migration references:

- Sonarr: <https://wiki.servarr.com/sonarr/postgres-setup>
- Radarr: <https://wiki.servarr.com/radarr/postgres-setup>
- Prowlarr: <https://wiki.servarr.com/prowlarr/postgres-setup>

## Validation

After Argo CD syncs `media-postgres`, verify the secret, StatefulSet, PVC, and
database list:

```sh
kubectl -n media get externalsecret media-postgres-auth media-postgres-arr-env
kubectl -n media get secret media-postgres-auth media-postgres-arr-env
kubectl -n media get statefulset,pod,pvc,svc -l app.kubernetes.io/name=media-postgres
kubectl -n media exec statefulset/media-postgres -- psql -U media_apps -d media_apps -c '\l'
```

The database list should include `sonarr-main`, `sonarr-log`, `radarr-main`,
`radarr-log`, `prowlarr-main`, and `prowlarr-log`.

## Backup And Restore

NFS snapshots protect the PostgreSQL volume, but application-ready restore
requires logical dumps. Before upgrades or storage maintenance, dump each app
database and keep the dump with the matching app config backup:

```sh
kubectl -n media exec statefulset/media-postgres -- pg_dump -U media_apps sonarr-main
kubectl -n media exec statefulset/media-postgres -- pg_dump -U media_apps radarr-main
kubectl -n media exec statefulset/media-postgres -- pg_dump -U media_apps prowlarr-main
```

For a full restore, restore the PostgreSQL PVC or recreate the databases from
logical dumps, restore each app's PVC backup, then re-sync Sonarr, Radarr,
and Prowlarr through Argo CD.
