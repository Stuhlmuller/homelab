# Prowlarr

Prowlarr uses the shared `media-postgres` PostgreSQL 14 instance for its
application and log databases. This app follows the Servarr PostgreSQL runbook:
`prowlarr-main` and `prowlarr-log` must exist before Prowlarr starts, and
Prowlarr is configured through `/config/config.xml` fields rather than an
application environment-variable override.

## PostgreSQL Configuration

The `configure-postgres` init container reads the `PROWLARR_POSTGRES_*` keys
from `media-postgres-arr-env`, then sets these `config.xml` entries on the
persistent `/config` volume:

```xml
<PostgresUser>media_apps</PostgresUser>
<PostgresPassword>runtime-secret-from-aws-ssm</PostgresPassword>
<PostgresPort>5432</PostgresPort>
<PostgresHost>media-postgres.media.svc.cluster.local</PostgresHost>
<PostgresMainDb>prowlarr-main</PostgresMainDb>
<PostgresLogDb>prowlarr-log</PostgresLogDb>
```

The database password comes from AWS SSM Parameter Store through External
Secrets. Do not commit it to this repository.

## Migration Notes

Prowlarr does not create its PostgreSQL databases and does not back them up. The
`media-postgres` init script creates `prowlarr-main` and `prowlarr-log`; backup
and restore coverage is tracked in `docs/storage-nfs.md`.

The Servarr Prowlarr PostgreSQL guide says the database user must be a
superuser for the housekeeping vacuum task. The `media-postgres` StatefulSet
uses the Docker official `POSTGRES_USER` bootstrap behavior, which creates
`media_apps` as the instance superuser on first initialization.

This deployment configures Prowlarr to use PostgreSQL but does not migrate
existing SQLite data from `/config/prowlarr.db`. To preserve existing data,
follow the upstream migration guide before treating the rollout as complete:

<https://wiki.servarr.com/prowlarr/postgres-setup>
