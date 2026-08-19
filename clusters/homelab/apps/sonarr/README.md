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

## Authentication

Sonarr runs behind Octelium and keeps local-address access unauthenticated for
the gateway path. The init container removes legacy `AuthenticationEnabled` and
`AuthenticationType` entries from `config.xml`, then writes:

```xml
<AuthenticationMethod>External</AuthenticationMethod>
<AuthenticationRequired>DisabledForLocalAddresses</AuthenticationRequired>
```

The app container also exports the matching `SONARR__AUTH__*` settings and
skips the linuxserver default config init script so the PVC-backed
configuration stays normalized after every restart.

### Verification

After Argo CD syncs this change, verify the rollout and runtime endpoint:

```bash
kubectl -n media rollout status deployment/sonarr --timeout=10m
kubectl -n media exec deploy/sonarr -c app -- \
  sh -ec 'grep -E "<(AuthenticationMethod|AuthenticationRequired|PostgresHost|PostgresMainDb|PostgresLogDb)>" /config/config.xml'
kubectl -n media exec deploy/sonarr -c app -- \
  sh -ec 'curl -fsS -o /dev/null http://127.0.0.1:8989/initialize.json'
```

Expected XML values:

```xml
<AuthenticationMethod>External</AuthenticationMethod>
<AuthenticationRequired>DisabledForLocalAddresses</AuthenticationRequired>
<PostgresHost>media-postgres.media.svc.cluster.local</PostgresHost>
<PostgresMainDb>sonarr-main</PostgresMainDb>
<PostgresLogDb>sonarr-log</PostgresLogDb>
```

If rollout status times out, inspect the init container and app logs before
retrying the sync:

```bash
kubectl -n media logs deploy/sonarr -c configure-postgres --tail=100
kubectl -n media logs deploy/sonarr -c app --tail=100
kubectl -n media describe pod -l app.kubernetes.io/name=sonarr
```

Failure modes to look for:

- `Sonarr config.xml is missing a closing </Config> tag`: restore the config PVC
  from backup before another rollout.
- `must contain exactly one AuthenticationMethod=External`: inspect the
  init-container output and the PVC-backed XML for malformed or multiline auth
  tags.
- `curl` probe failures with clean XML: inspect app logs for PostgreSQL
  connectivity or migration failures before changing auth settings.

### Rollback

Rollback through GitOps, not a live manual patch. Revert the commit that changed
`clusters/homelab/apps/sonarr/values.yaml`, open the normal PR, wait for CI, and
let Argo CD sync `main`.

If emergency access must temporarily return to built-in Forms auth, make that a
repo change too: remove the `SONARR__AUTH__*` environment keys and the
`AuthenticationMethod`/`AuthenticationRequired` writes, remove the command that
skips `/etc/cont-init.d/30-config`, and document the temporary operator
credentials source before opening the rollback PR. Preserve the PostgreSQL tags
unless intentionally rolling Sonarr back to SQLite from a verified backup.

## Media Storage

Sonarr mounts the static `media-tv` PVC at `/tv` and the shared
`media-downloads` PVC at `/downloads`. Both claims point at the QNAP `/media`
NFS export instead of the default `/homelab` provisioner path.

The `media-tv-migration` Job copies files from the older `sonarr-media` PVC into
`/media/tv`, sets write-friendly NFS permissions, and verifies that the target
path can be written before the app switches to the new claim. The older
`sonarr-media` claim remains in desired state as the migration source and
rollback reference until the copy is verified.

## Migration Notes

The Servarr guide requires Sonarr `v4.0.0.615` or newer. The Git baseline pins
the `lscr.io/linuxserver/sonarr` `4.0.15` release with a digest, which satisfies
that version floor while keeping the deployed image immutable and reviewable.

Sonarr does not create its PostgreSQL databases and does not back them up. The
`media-postgres` init script creates `sonarr-main` and `sonarr-log`; backup and
restore coverage is tracked in `docs/storage-nfs.md`.

This deployment configures Sonarr to use PostgreSQL but does not migrate
existing SQLite data from `/config/sonarr.db`. To preserve existing data,
follow the upstream migration guide before treating the rollout as complete:

<https://wiki.servarr.com/en/sonarr/postgres-setup>
