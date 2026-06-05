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
`<AuthenticationType>DisabledForLocalAddresses</AuthenticationType>` plus
`<AuthenticationRequired>DisabledForLocalAddresses</AuthenticationRequired>` in
`/config/config.xml`. The Servarr FAQ documents `AuthenticationType` as the
config-file equivalent for this setting, while the environment variable table
uses `AuthenticationRequired`, so the startup reset writes both names.
The Radarr app container also sets `RADARR__AUTH__METHOD=External` and
`RADARR__AUTH__REQUIRED=DisabledForLocalAddresses`, because Radarr environment
variables override persisted `config.xml` entries at startup and keep the
running process aligned if the PVC copy drifts back to Forms authentication or
password-required mode.
Radarr is exposed only through the tailnet Istio route with Funnel disabled, so
the tailnet gateway is the external access boundary and Radarr's own password
prompt is intentionally disabled.

This avoids recurring lockouts when the internal Radarr username/password state
drifts or is reset during config/database migrations. If Radarr is ever exposed
outside the tailnet, restore Forms authentication or add a dedicated forward
auth layer before rollout. Upstream documents `External` as the config-file-only
mode for deployments protected by external authentication:
<https://wiki.servarr.com/radarr/faq#authentication-method>.

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
the `lscr.io/linuxserver/radarr` `5.27.5` release with a digest, which satisfies
that version floor while keeping the deployed image immutable and reviewable.

Radarr does not create its PostgreSQL databases and does not back them up. The
`media-postgres` init script creates `radarr-main` and `radarr-log`; backup and
restore coverage is tracked in `docs/storage-nfs.md`.

This deployment configures Radarr to use PostgreSQL but does not migrate
existing SQLite data from `/config/radarr.db`. To preserve existing data,
follow the upstream migration guide before treating the rollout as complete:

<https://wiki.servarr.com/radarr/postgres-setup>
