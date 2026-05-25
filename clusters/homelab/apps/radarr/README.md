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
