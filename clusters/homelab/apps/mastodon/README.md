# Mastodon

Preparation for the requested Mastodon server for stinkyboi.com. This directory
owns PostgreSQL, Redis, retained storage, web, Sidekiq, streaming, and a schema
migration Job. The shared Terragrunt stack declares its Application at
`IaC/live/argocd-apps/mastodon`; the draft has not been merged or applied, and
no server or public route is deployed. The declared Istio route sends streaming requests to port
4000 and remaining subdomain requests to Puma on port 3000. STRICT mTLS and
default-deny authorization admit only the shared gateway and Mastodon service
account; NetworkPolicy separately limits ingress and federation egress. This
The shared cloudflared configuration declares its native public route;
`mastodon-public-dns.yml` publishes only the instance hostname after rollout
readiness. Neither has been applied yet. The website uses `mastodon.stinkyboi.com`; account identities
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
PEM; it never persists another key pair or logs keys. SMTP passwords mount as
a separate file and enter the native process directly, avoiding dotenv variable
expansion or quote escaping. Its regression test proves
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

## Application registration

`IaC/stacks/mastodon/stack.hcl` uses the shared Application template, source
revision `main`, and the existing `homelab` AppProject because its retained
local storage needs PersistentVolume and StorageClass permissions. The project
allows the Mastodon namespace explicitly. Dependencies order registrations;
they do not prove runtime readiness.

After all activation gates are satisfied and the reviewed change is on `main`,
dispatch `terragrunt-apply.yml` with `argocd_app=mastodon` and exact current
`main` as `expected_sha`. The targeted path checks upstream health, CRDs,
namespace secret-store access, and storage permissions before any write;
then plans/applies declared SSM/IAM prerequisites and this Application using
checked saved plans. It does not reconcile unrelated application registrations.
Review the private SSM plan before authorizing production because its shared
catalog can contain other pending declarations. Confirm Argo observes the
merged revision, migrations finish, and each process rolls out before testing
public behavior. Do not dispatch while provider settings still contain
placeholders or publication lacks complete-pull evidence.

## Public DNS activation

After reviewed `main` has reconciled Mastodon and `octelium-public`, dispatch
`mastodon-public-dns.yml` with that exact commit as `expected_sha`. It refuses
publication until both Applications are Synced/Healthy at the reviewed revision.
The protected job reads only the existing Cloudflare DNS token and tunnel ID,
then creates or updates the tagged `mastodon.stinkyboi.com` CNAME. It refuses
foreign records, conflicting A/AAAA records, duplicate records, and incomplete
pagination. It never deletes records or republishes private application names.

The retained connector now includes Mastodon, so its retirement needs a reviewed
replacement for this public transport. The existing private DNS inventory does
not manage this hostname. Keep the shared tunnel until that replacement has
passed real federation acceptance. To roll back activation, first disable
Mastodon's public route through reviewed code; preserve its data and credentials.
The DNS helper deliberately provides no deletion path: add a reviewed retirement
contract before removing the record. For tunnel relocation, update only the
owned record through this workflow after the replacement connector is ready.

## Remaining deployment gates

- Publish both official Mastodon 4.7.3 images from PR #1288 through the reviewed
  Harbor workflow; prove complete destination pulls before consumption. On
  2026-10-11, run `38196403709` passed validation but its copy job remained
  pending in the shared `harbor-packages-production` publication lane. This is
  a delivery-queue dependency, not a Mastodon application dependency. A queued
  copy job is not a publication receipt.
- Add apex WebFinger delegation so accounts at `stinkyboi.com` are discoverable
  while the website stays on `mastodon.stinkyboi.com`. Do not change the local
  account domain after creating identities.
- Add admin bootstrap and supply the selected email provider settings/credential.
- Render and exercise the configuration template, migrations, and full image
  startup after domain/mail selection; static checks do not prove runtime boot.
- Activate and verify the declared public route and DNS without restoring
  private applications' retired public routes. Existing Funnel policy admits only the
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
