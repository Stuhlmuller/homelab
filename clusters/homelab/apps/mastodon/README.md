# Mastodon

Preparation for the requested Mastodon server for stinkyboi.com. This directory
owns PostgreSQL, Redis, retained storage, web, Sidekiq, streaming, and a schema
migration Job. No Argo CD Application registers it yet; no server or public
route is deployed. The declared Istio route sends streaming requests to port
4000 and remaining subdomain requests to Puma on port 3000. STRICT mTLS and
default-deny authorization admit only the shared gateway and Mastodon service
account; NetworkPolicy separately limits ingress and federation egress. This
route still needs a public transport and DNS declaration. The website uses `mastodon.stinkyboi.com`; account identities
use `stinkyboi.com`. This preserves the existing apex portal and requires a
public apex WebFinger delegation route. Mail settings remain explicit
`REPLACE_ME` placeholders, which the Rails launcher rejects.

## Storage and credentials

PostgreSQL 18 and Redis 7.4 use separate retained local volumes on `zimaboard-0`,
following the existing media PostgreSQL pattern. QNAP NFS stalls documented in
`docs/storage-nfs.md` make it unsuitable for the active database. Redis keeps
Sidekiq queues with AOF and `appendfsync everysec`, allowing up to one second of
queue loss after an abrupt host failure.

The local claims request 3 GiB and 1 GiB. These are descriptive capacities:
`hostPath` does not enforce quotas. Before registration, recheck node memory,
filesystem headroom, and image download space. The node had approximately
7.2 GiB free disk and 2.3 GiB available memory on 2026-10-11. Grow or move storage
before consuming that headroom. A node reset or disk failure loses local data.

A bounded root init container changes only the mounted directory's ownership;
PostgreSQL and Redis run as UID/GID 65534. PostgreSQL initializes `pg_trgm` and
`unaccent`, then removes superuser privileges from the application role.

Terragrunt generates `/homelab/mastodon/postgres-password` and
`/homelab/mastodon/redis-password` in encrypted state/SSM. The ExternalSecret
mounts the credentials as files. Its namespace policy permits only the
Mastodon prefix. Rotation needs a declared ExternalSecret revision and workload
restart through GitOps, plus database/Redis password coordination.

## Server configuration

The official 4.7.3 image serves compiled static files and media through Puma;
streaming runs separately on port 4000. A wave-1 migration Job prepares the
schema before wave-2 Deployments start. Web and Sidekiq mount the retained media
claim, writable bounded temporary/log directories, and read-only configuration.
Sidekiq runs five threads; Puma runs one worker with five threads to fit the
small homelab. Sidekiq startup/readiness checks use the upstream job-processing
marker, cleared by the launcher before each restart to prevent stale readiness.
Recheck complete-server resource requests before registration.

The [External Secrets template](https://external-secrets.io/latest/guides/templating/#templatefrom)
combines committed settings and SSM credentials into mounted `.env.production`
and `streaming.env` files. Streaming receives only its own configuration file.
SSM also generates stable Rails, Active Record encryption, and P-256 VAPID keys.
The Ruby launcher derives the raw base64url Web Push key pair from the mounted
PEM; it never persists another key pair or logs keys. Its regression test proves
conversion, command forwarding, and rejection of placeholders and invalid keys.

Keep encryption and VAPID keys with encrypted-state backups. Recreating them
during restore would invalidate encrypted records, sessions, or push clients.
`OnChange` ExternalSecrets and subPath mounts require a declared secret/template
revision and Deployment runtime revision to consume changes; SSM edits alone
do not refresh running processes. Admin bootstrap still needs the administrator details. For SMTP activation,
select the provider and commit its non-secret host, login, and sender settings
in `configmap.yaml`. Set `MASTODON_SMTP_PASSWORD` in the protected GitHub
production environment, then run `mastodon-smtp-credential.yml` with exact
current `main` as `expected_sha`. It validates the declared SecureString and
stores only `/homelab/mastodon/smtp-password`, using a private temporary file;
it neither changes application keys nor claims provider authentication works.
Advance the runtime ExternalSecret and Deployment revisions through GitOps,
then send and receive a real email. Failed delivery is an activation failure.
The workflow is also the password-rotation path; preserve the prior protected
credential until the new value works, so it can be restored through this path.

## Backup and restore

The nightly `mastodon-backup` CronJob connects over the database's local Unix
socket, creates a custom-format dump, verifies the dump catalog and checksum,
and atomically publishes it to the retained NFS backup claim. It retains
14 days. Failed dumps stay unpublished. This is a database backup only; media
and stable application keys still need their final backup contract. NFS media
and backups share a NAS and do not protect against NAS loss.

Before acceptance, prove a successful scheduled backup and restore the newest
dump into an isolated PostgreSQL instance. Verify tables, accounts, and media
references before trusting the restore. Recreate the non-superuser role and
extensions from `initdb-configmap.yaml`; restore with `pg_restore --no-owner`
into the initialized `mastodon` database. Stop application writes through
repository-owned desired state before a production restore. Never overwrite an
active writer's database. Preserve local claims until recovery is verified.

## Remaining deployment gates

- Publish both official Mastodon 4.7.3 images from PR #1288 through the reviewed
  Harbor workflow; prove complete destination pulls before consumption. On
  2026-10-11, run `38196403709` passed validation but its copy job queued behind
  NOFX run `38173056151`, awaiting `homelab-production` approval in the shared
  `harbor-packages-production` lane. The owner must resolve that earlier run;
  a queued copy job is not a publication receipt.
- Add apex WebFinger delegation so accounts at `stinkyboi.com` are discoverable
  while the website stays on `mastodon.stinkyboi.com`. Do not change the local
  account domain after creating identities.
- Add admin bootstrap and supply the selected email provider settings/credential.
- Render and exercise the configuration template, migrations, and full image
  startup after domain/mail selection; static checks do not prove runtime boot.
- Declare a dedicated public federation route and DNS without restoring private
  applications' retired public routes. Existing Funnel policy admits only the
  two reviewed callbacks, so it cannot serve this custom-domain website as-is.
- Register through the shared Terragrunt Application template after rendering,
  policy checks, capacity checks, secret readiness, and image publication.
- Verify public browser login, email, WebFinger, remote federation, persistent
  posting/media, streaming, and backup/restore before reporting the server ready.

Validate preparation:

```sh
kubectl kustomize clusters/homelab/apps/mastodon > /tmp/mastodon.yaml
nix develop --command conftest test --policy policy /tmp/mastodon.yaml
nix develop --command conftest verify --policy policy
nix develop --command python3 scripts/ci/harbor-images-check.py
nix develop --command ruby scripts/ci/mastodon-launch-test.rb
```

Rollback before registration is removal of this preparation. After registration,
revert the Application/workload change through protected `main`; retained PVs,
PVCs, SSM keys, and backups must remain available for recovery.
