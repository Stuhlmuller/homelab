# Sonarr

Sonarr uses the shared `media-postgres` PostgreSQL 14 instance for its
application and log databases. This app follows the Servarr PostgreSQL runbook:
`sonarr-main` and `sonarr-log` must exist before Sonarr starts, and Sonarr is
configured through `/config/config.xml` fields rather than an application
environment-variable override.

## PostgreSQL Configuration

The `configure-postgres` init container reads the `SONARR_POSTGRES_*` keys from
`media-postgres-arr-env`, then sets these `config.xml` entries on the
persistent `/config` volume:

```xml
<PostgresUser>media_apps</PostgresUser>
<PostgresPassword>runtime-secret-from-aws-ssm</PostgresPassword>
<PostgresPort>5432</PostgresPort>
<PostgresHost>media-postgres.media.svc.cluster.local</PostgresHost>
<PostgresMainDb>sonarr-main</PostgresMainDb>
<PostgresLogDb>sonarr-log</PostgresLogDb>
```

The database password comes from AWS SSM Parameter Store through External
Secrets. Do not commit it to this repository.

## Migration Notes

The Servarr guide requires Sonarr `v4.0.0.615` or newer. This deployment uses
`lscr.io/linuxserver/sonarr:4.0.15`, which satisfies that version floor.

Sonarr does not create its PostgreSQL databases and does not back them up. The
`media-postgres` init script creates `sonarr-main` and `sonarr-log`; backup and
restore coverage is tracked in `docs/storage-nfs.md`.

This deployment configures Sonarr to use PostgreSQL but does not migrate
existing SQLite data from `/config/sonarr.db`. To preserve existing data,
follow the upstream migration guide before treating the rollout as complete:

<https://wiki.servarr.com/en/sonarr/postgres-setup>
