# Mastodon

Mastodon server for stinkyboi.com. This directory owns PostgreSQL, Redis,
retained storage, web, Sidekiq, streaming, and schema migration. The shared
Terragrunt stack declares its Application at `IaC/live/argocd-apps/mastodon`;
registration and public activation follow the gates below.

The Istio route sends streaming requests to port 4000 and remaining instance
requests to Puma on port 3000. STRICT mTLS and default-deny authorization admit
only the shared gateway and Mastodon service account. NetworkPolicy separately
declares ingress and federation-egress intent. The shared cloudflared route and
`mastodon-public-dns.yml` provide public transport and publish the instance
hostname after rollout readiness.

Website and account identities both use `mastodon.stinkyboi.com`, preserving
the private apex portal and independent federation discovery. Owner bootstrap
creates `rodman` with `rodman@stuhlmuller.net`. Google Workspace SMTP uses
`smtp.gmail.com:587`, the same login and sender address. Inject the protected
SMTP credential before registration; the Rails launcher rejects placeholders.
The public egress policy allows TCP 80/443 for federation and the configured
SMTP port 587 for web and Sidekiq. It does not open implicit TLS port 465; the
mounted runtime config uses STARTTLS on 587. Qualify remote federation and
email delivery under the canary policy before enforcing this boundary.

## Storage and credentials

PostgreSQL 18 and Redis 7.4 use separate retained local volumes on `zimaboard-1`,
following the existing media PostgreSQL pattern. QNAP NFS stalls documented in
`docs/storage-nfs.md` make it unsuitable for the active database. Redis keeps
Sidekiq queues with AOF and `appendfsync everysec`, allowing up to one second of
queue loss after an abrupt host failure.

The local claims request 3 GiB and 1 GiB. These are descriptive capacities:
`hostPath` does not enforce quotas. Before registration, recheck node memory,
filesystem headroom, and image download space. The 2026-10-18 preflight found
approximately 11.8 GiB free disk, 2.4 GiB available memory, and 4.25 GiB of
unreserved memory on `zimaboard-1`. PostgreSQL (256 MiB), Redis (64 MiB), and
the backup Job (64 MiB) reserve 384 MiB together. Redis retains its 512 MiB
limit; verify actual memory use after startup.

The original `zimaboard-0` placement had only 5 MiB of unreserved memory at
that preflight. Initial placement moved before any Mastodon Application or
local volumes existed; the backup Job follows the same node for its database
Unix socket. Do not retarget a bound local volume by editing affinity: use an
explicit backup and restore. A node reset or disk failure loses local data.
Grow or move storage before consuming its headroom.

A bounded root init container changes only the mounted directory's ownership;
PostgreSQL and Redis run as UID/GID 65534. PostgreSQL initializes `pg_trgm` and
`unaccent`. PostgreSQL 18 protects the bootstrap role `mastodon` from demotion;
its administrator credential stays in the datastore Secret and PostgreSQL Pod.
A wave-0 database-role hook provisions the separate `mastodon_app` role with
its own generated password and no superuser, role-creation, database-creation,
replication, or RLS-bypass privileges. It uses the local database socket, keeps
system-catalog ownership intact, and never resets the data directory. Unexpected
bootstrap-owned application objects stop the hook for a reviewed ownership
migration rather than silently changing existing data.

Terragrunt generates `/homelab/mastodon/postgres-password` and
`/homelab/mastodon/redis-password` in encrypted state/SSM. The separate
`/homelab/mastodon/postgres-app-password` supplies `mastodon_app`; only that
PostgreSQL credential enters application configuration. Redis mounts only its
own password key. The ExternalSecrets mount credentials as files. Its namespace policy permits only the
Mastodon prefix. Rotation needs a declared ExternalSecret revision and workload
restart through GitOps, plus database/Redis password coordination.

## Server configuration

The official 4.7.3 image serves compiled static files and media through Puma;
streaming runs separately on port 4000. The image's private application directory
requires its native UID/GID 991; application containers use those IDs with
supplementary filesystem group 65534 for shared volumes. The datastore and
backup containers retain UID/GID 65534. The service account, config, secrets
and storage precede PostgreSQL in wave -2. PostgreSQL rolls in wave -1 before
database-role provisioning in wave 0, schema preparation in wave 1, owner
bootstrap in wave 2, and the Deployments start in wave 3. Web, Sidekiq, streaming
and migration/owner Jobs select Acer for memory headroom. PostgreSQL and Redis
retain local data on `zimaboard-1`; backups run there to reach the local database
socket and write dumps to NFS. Migration Secret
projection requires the `runtime-v2` key, rendered atomically with the app-role
credentials; an old Ready status cannot let the hook mount v1 credentials. Web and Sidekiq mount the retained media
claim, writable bounded temporary/log directories, and read-only configuration.

The Ruby launcher creates a private `0700` directory under the writable `/tmp`
volume for upload processing. The volume root is group-managed by Kubernetes
and lacks the sticky bit Ruby requires for a shared temporary directory.
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
do not refresh running processes. The owner and non-secret Google Workspace settings are committed. For SMTP
activation, supply the account app credential through the protected workflow. Set `MASTODON_SMTP_PASSWORD` in the protected GitHub
production environment, then run `mastodon-smtp-credential.yml` with exact
current `main` as `expected_sha`. It validates the declared SecureString and
stores only `/homelab/mastodon/smtp-password`, using a private temporary file;
it neither changes application keys nor claims provider authentication works.
Advance the runtime ExternalSecret and Deployment revisions through GitOps,
then send and receive a real email. Failed delivery is an activation failure.
The workflow is also the password-rotation path; preserve the prior protected
credential until the new value works, so it can be restored through this path.

The first 2026-10-18 rollout confirmed PostgreSQL 18 rejects demoting its
bootstrap superuser, and the upstream application directory rejects UID 65534.
The database still had zero application tables. The role split and native-image
UID fix preserve that cluster; the PostgreSQL regression test verifies password
authentication, limited privileges, repeat preservation, catalog ownership and
fail-closed handling of unexpected existing data. It runs in the offline gate;
`--pg-bin /path/to/postgresql-18/bin` selects a PostgreSQL 18 installation for
the protected-bootstrap regression.

## Initial owner

The wave-2 `mastodon-owner-bootstrap` hook uses the upstream account-creation
fields to create `rodman` as a confirmed, approved Owner. It reads the generated
`/homelab/mastodon/admin-password` through a file mounted only into that Job.
Later syncs preserve the account and password; a conflicting email, role, or
confirmation state stops bootstrap instead of replacing or promoting a user.
No initial password is printed. Native password changes remain native; SSM is
only the initial bootstrap/recovery slot and must not be assumed current afterward.

Before acceptance, retrieve the initial credential only through an authorized
private operator read, then prove browser login and Owner administration. Do
not paste the credential into chat or commit it. Preserve account/database and
stable application keys through rollback; rerunning the hook is not a password
reset mechanism. Tests verify first creation, repeat preservation, conflict
refusal, and error containment. Actual Rails persistence is verified after rollout.

## Browser acceptance

Public acceptance on 2026-10-25 verified HTTPS/API and ActivityPub metadata,
browser owner sign-in and Home navigation, private-post/media read-back,
authenticated public WebSocket delivery, and native remote-account resolution.
Anonymous API requests cannot read the private test posts. The pinned 4.7.3 admin dashboard loads, but emits
a React Router `Invariant failed` error from `react-router-dom-C1dtKQUg.js`.
Client-side dashboard widgets remain an open validation finding; inspect that
bundle and its router context before treating those widgets as verified.

## Backup and restore

The nightly `mastodon-backup` CronJob connects over the database's local Unix
socket, creates a custom-format dump, verifies the dump catalog and checksum,
and atomically publishes it to the retained NFS backup claim. It retains
14 days. Failed dumps stay unpublished. This is a database backup only; media
and stable application keys still need their final backup contract. NFS media
and backups share a NAS and do not protect against NAS loss.

The one-shot `mastodon-initial-backup-v1` Job runs the nightly backup template
at sync wave 3 after owner bootstrap. The subsequent
`mastodon-restore-verification-v2` Job runs the scheduled verifier template at
wave 4, restoring the newest checksum-verified NAS dump immediately after
rollout. The `mastodon-restore-verification` CronJob repeats this rehearsal at
03:35 America/Los_Angeles, after the 03:00 backup's 30-minute execution window.
Both verifier paths use disposable PostgreSQL 18 storage, a read-only backup
mount, no production database volume or credentials, and a private Unix socket.
Success checks the restored schema, owner and media catalog. It does not prove
media-file or stable application-key recovery.

Kustomize copies each scheduled Job template into its corresponding initial
Job. Version an initial Job name when changing its copied template; completed
Kubernetes Job templates are immutable. The nightly verifier prevents the
original one-shot result from becoming the only recovery evidence.

Before acceptance, prove a successful scheduled backup and restore the newest
dump into an isolated PostgreSQL instance. Verify tables, accounts, and media
references before trusting the restore. Initialize the extensions and limited application role from
`initdb-configmap.yaml`; restore with
`pg_restore --no-owner --no-comments --role=mastodon_app` into the initialized
`mastodon` database. The bootstrap administrator owns the extensions; their
comments are omitted rather than granting the application administrator rights. Stop application writes through
repository-owned desired state before a production restore. Never overwrite an
active writer's database. Preserve local claims until recovery is verified.

## Application registration

`IaC/homelab/us-west-2/apps/mastodon/stack.hcl` uses the shared Application template, source
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

## Publication recovery evidence

Scoped run `38210448448`, attempt 2, passed validation and failed the web image
at `destination-copy` on 2026-10-12 06:24 UTC. Read-only registry logs showed
an interrupted blob PATCH with `unexpected EOF` and client disconnect at
06:24:48 UTC. The declared Istio upload timeout is disabled. This supports a
bounded transfer retry, not digest/alias/pull bypass or database modification.
The failed client stderr remains private, so its full cause is not proven.

Attempt 3 repeated the same web-image `destination-copy` failure at
06:40:14 UTC. Do not continue blind copy retries. Matching registry evidence
again showed client disconnect/`unexpected EOF`; live nginx settings had no
body-size limit, request/response buffering disabled, and 900-second proxy
send/read timeouts. No causal gateway/body-limit error was established. Recover
the private client diagnostic through a reviewed secret-safe path before the
next write attempt; do not print raw client stderr into public Actions logs.

Earlier streaming scans reported a duplicate
`scan_report_digest_registration_uuid_mime_type_key` at 06:22:28 UTC. This is
separate from the web-image copy failure and needs Harbor scan/readiness
follow-up before treating vulnerability coverage as complete. Preserve registry
content and schema; source evidence is the failed run's sanitized status and
Harbor core/registry/PostgreSQL logs for that interval. A failed or partial
publication never authorizes consuming references.

PR #1298 merged the operator-approved ciphertext-only diagnostics with one-day
retention and pinned primary/encryption-subkey fingerprints. Scoped run
38508845110 on main deeaa9982be617813cb0973a4e33e9ce3264241f passed on
2026-10-14: all four Mastodon scope entries completed digest-preserving copies,
aliases and fresh authenticated destination pulls. No failure artifact was
needed. This proves publication recovery; the earlier EOF cause remains unproven.

PR #1308 merged the Ruby validation toolchain into main at
a435d6ffad694ebf3ea24563cf9aee01e43c0f6a. Refresh the fixed Mastodon receipt
after the PostgreSQL candidate prerequisite: ancestor reuse requires a
byte-identical publication bundle, including flake.nix and flake.lock.

## Scan acceptance evidence

Read-only Harbor API inspection on 2026-10-14 found completed scan summaries
for the published index digests and Mastodon amd64/arm64 children. PostgreSQL
reported 16 Critical package findings, Redis zero, and web/streaming one each.
Digest-verified immutable upstream indexes and read-only Harbor child metadata
confirmed complete runnable-platform coverage: PostgreSQL has five Linux
platforms, each with 16 Critical findings; Redis has eight, each with zero
Critical findings. All missing scan summaries match attestation-manifest
descriptors with unknown/unknown platforms: five for PostgreSQL, eight for
Redis. Those are not runnable platform images or zero-CVE scan results.

PR #1309 merged a separate PostgreSQL 18-bookworm candidate at
afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c.
Its amd64 configuration retains PostgreSQL 18.6, Debian Bookworm and
/var/lib/postgresql/18/docker. The existing Harbor database pin is preserved.
Publication and fresh scans must precede Mastodon consumption; the newer digest
alone is not evidence of remediation.

The candidate index and its amd64/arm64 children completed fresh Harbor scans
with four Critical findings each. The inspected amd64 child is
9551dd5bf356409a21b31248f49b33bba9bb1877365f3a7e933aecd9af3cf52d.
Remaining findings: libsqlite3-0
CVE-2025-7458, libxml2 CVE-2026-6653, zlib1g CVE-2023-45853 and Go stdlib
CVE-2025-68121. The 12 Perl findings no longer appear. Exact image-layer
inspection verified patched Perl 5.36.0-7+deb12u4 and unchanged SQLite, libxml2
and zlib package versions. Scoped publication run 38516246033 on main
fcba3da76643f67c76ddffc086948967fc3f708d succeeded at 2026-10-14 05:43 UTC.
All four fixed images passed digest-preserving copies, aliases and complete
authenticated destination pulls. No failure artifact was emitted. The draft
now uses this candidate for database, init and backup callers; Harbor retains
its old pin. Runtime CVE applicability still needs acceptance; delivery does
not waive package findings.

Exact entrypoint inspection found gosu invoked only when PostgreSQL starts as
UID 0. The declared database runs as UID 65534; its root directory init replaces
the entrypoint with bounded chown/chmod commands. Password checks and backups
also replace the entrypoint. The bundled gosu binary contains Go 1.24.6 metadata,
consistent with the stdlib finding. The
[Go advisory](https://pkg.go.dev/vuln/GO-2026-4337) concerns TLS session resumption
with changed certificate-authority configuration. Keep the package finding;
this execution-path evidence does not clear the SQLite or libxml2 findings.
Exact ELF dynamic dependencies show no direct SQLite linkage from the database
binary or declared pg_trgm/unaccent extensions. The database does link libxml2.
Database ingress is limited to Mastodon pods with the declared Istio principal
and NetworkPolicy; the application uses the separate limited `mastodon_app`
role. The bootstrap administrator remains private to datastore-local Jobs.
Do not expose a public SQL endpoint or
interpret isolation as a package fix. Verify loaded libraries and app behavior
on the actual workload before public acceptance.

Read-only live checks on 2026-10-25 confirmed PostgreSQL 18.6 runs directly as
`postgres`, the bootstrap administrator retains OID 10, and `mastodon_app` has
none of the five elevated role flags. The server maps libxml2 and zlib, with no
SQLite mapping; the application schema has no XML columns. These checks retain
the installed-package findings, including the loaded libxml2 finding.
Puma maps the JSON 2.21.2 parser/generator, and streaming uses
`TRUSTED_PROXY_IP=loopback,uniquelocal` on the actual workload.

Debian's [zlib advisory](https://security-tracker.debian.org/tracker/CVE-2023-45853)
records that Bookworm does not build the affected contrib/minizip code from
src:zlib. This explains the zlib1g installed-package finding; retain it without
scanner suppression. The
[SQLite advisory](https://security-tracker.debian.org/tracker/CVE-2025-7458)
still marks Bookworm vulnerable and requires arbitrary crafted SQL execution.
The [libxml2 advisory](https://security-tracker.debian.org/tracker/CVE-2026-6653)
also remains unfixed in Bookworm. Neither is cleared by the candidate's newer
tag; use fresh package scans and actual PostgreSQL feature usage for acceptance.

| Image                    | Critical finding                                                                                                                                                       | Required follow-up                                                                    |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| PostgreSQL 18.6-bookworm | Perl CVE-2026-13221, CVE-2026-42496 and CVE-2026-8376 across four packages; SQLite CVE-2025-7458; libxml2 CVE-2026-6653; zlib CVE-2023-45853; Go stdlib CVE-2025-68121 | Verify distro/helper applicability; use a compatible patched official image.          |
| Mastodon web             | JSON 2.18.0, CVE-2026-33210                                                                                                                                            | Verify the exact active bundle: upstream 4.7.3 locks JSON 2.21.2.                     |
| Mastodon streaming       | proxy-addr 2.0.7, CVE-2026-90711; fixed version 2.0.8                                                                                                                  | Check trust-proxy applicability or pin a patched dependency before public activation. |

Exact web-image inspection of amd64 child
189964b9e0c45c55ab8c600c21449e05977550a120c5e84d996aed499a45d522
verified its manifest hash and read layer files without executing the image.
The vulnerable JSON 2.18.0 specification is a Ruby default gem under
/usr/local/lib/ruby/gems/4.0.0/specifications/default. The application lockfile
selects JSON 2.21.2, which is installed under /usr/local/bundle/specifications;
GEM_HOME points to /usr/local/bundle. Web, worker, migration and owner-bootstrap
commands all enter bundle exec. The launcher requires OpenSSL, Base64 and
FileUtils, not JSON. Thus the reported 2.18.0 default gem is outside the declared
application bundle. Retain the installed-package finding; runtime acceptance
must still verify the loaded gem version on the real workload.

Streaming trust is explicit: loopback,uniquelocal, matching the upstream default.
A local reproduction against proxy-addr 2.0.7 reproduced the unsafe mapped-IPv6
subnet case and proved this configuration rejects public IPv4, mapped IPv4 and
IPv6 test addresses. The
[vendor advisory](https://github.com/jshttp/proxy-addr/security/advisories/GHSA-jqcg-44mw-7w3h)
requires unsafe mapped/zero-prefix IPv6 trust entries; this declaration contains
neither. Retain the scan finding and prefer the patched dependency on a future
verified upstream update; this is applicability evidence, not a scanner exclusion.

Sources: [Harbor collector/client](../harbor/vulnerability-exporter.py),
[JSON vendor advisory](https://github.com/ruby/json/security/advisories/GHSA-3m6g-2423-7cp3),
[Mastodon 4.7.3 lockfile](https://github.com/mastodon/mastodon/blob/v4.7.3/Gemfile.lock),
[proxy-addr CVE](https://nvd.nist.gov/vuln/detail/CVE-2026-90711), and
[Debian zlib tracking](https://security-tracker.debian.org/tracker/CVE-2023-45853).
These are triage findings, not scan-policy overrides or accepted deployment risk.

## Remaining deployment gates

- Publish the fixed four-image Mastodon scope through the reviewed Harbor
  workflow: PostgreSQL, Redis, Mastodon web and streaming. PR #1296 added this
  scope; public mirrors now have their dedicated production publication lane.
  Require exact digest/platform checks and complete authenticated destination
  pulls before consumption. The earlier shared-queue delay is resolved; the
  web destination-copy failure is recovered by scoped run 38508845110; refresh
  the refreshed fixed-scope receipt is run 38516246033 after Ruby and candidate
  prerequisites. Recheck bundle equality if main advances before registration.
- Keep `LOCAL_DOMAIN=mastodon.stinkyboi.com` stable once accounts exist. The
  private apex is not part of this instance's discovery or public routing.
- Supply the Google Workspace SMTP app credential through the protected
  injection workflow, then verify owner bootstrap and actual email receipt.
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
revert the Application/workload change through protected `main`. The namespace,
local StorageClasses, PVs, and PVCs carry `Prune=false,Delete=false` so deleting
the Application retains claims for recovery. Preserve SSM keys and backups too.

## Private client access

The catalog declares a non-anonymous `mastodon.default` Octelium WEB Service.
It requires `homelab-human-web-access`, preserves Mastodon's bearer token,
and forwards the original HTTPS host to Istio. `isPublic: true` enables the
clientless HTTPS listener; it does not grant anonymous access.

Establish this Service before restricting the tunnel paths. From reviewed
`main`, using an authenticated Octelium operator session:

```sh
yq ea 'select(.kind == "Service" and .metadata.name == "mastodon") | .metadata.name = "mastodon.default"' \
  docs/examples/octelium/homelab-services.yaml > /tmp/mastodon-service.yaml
octeliumctl apply --domain stinkyboi.com --include Service /tmp/mastodon-service.yaml
octeliumctl get service mastodon.default --domain stinkyboi.com -o json
```

Verify anonymous access is disabled and the human policy is attached; repeat
apply must report no changes. Do not apply/prune the complete shared catalog
for this single-Service change. The tunnel bypasses human access only for the federation allowlist below.

### Public federation boundary

The tunnel matches an anchored allowlist before its authenticated Octelium
fallback. Only WebFinger/host-meta, instance actor/inboxes, canonical `/ap/`
ActivityPub resources, legacy `/users/` resources, contexts, collections,
emojis and local attachment/thumbnail/avatar/header/emoji files remain anonymous.
The path grammar excludes dot segments, encoded escapes and arbitrary media
suffixes; tests exercise cloudflared's actual matcher, including encoded bypasses.

All other paths require Octelium human access: root/web UI, login/recovery,
settings, admin/Sidekiq/PgHero, OAuth, all REST APIs, streaming, NodeInfo,
static application assets, media proxy and backup downloads. Mastodon's own
login/permissions remain required after Octelium. Native clients need private
Octelium access; anonymous Internet API/OAuth access is intentionally removed.
Browser profile/post links (`/@...`) also require human access; remote servers
can still discover accounts with WebFinger and fetch canonical ActivityPub IDs.

Acceptance: anonymous `/admin`, `/auth/sign_in`, `/api/v1/streaming` and `/`
must reach Octelium authentication, never Mastodon; actor/WebFinger and a real
media URL must remain accessible. Verify a signed federation fetch, owner login,
REST posting and streaming through the authenticated/private path. No public
allowlist expansion without checking Mastodon route ownership again.

Rollback through a reviewed PR reverting the tunnel config and its Deployment
revision; preserve the authenticated Service and all retained data.

The allowlist follows [Mastodon 4.7.3 route ownership](https://github.com/mastodon/mastodon/blob/v4.7.3/config/routes.rb)
and [attachment serialization](https://github.com/mastodon/mastodon/blob/v4.7.3/app/serializers/activitypub/note_serializer.rb).
[Cloudflared matches rules in order](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/configuration-file/);
the first Mastodon rule is the narrow exception, the second requires Octelium.

On 2026-10-25 the initial-backup and isolated restore-verification Jobs completed
successfully at revision `ce28791046ced6805c0a0df1397c382f227e67dc`; Argo reported
Synced/Healthy/Succeeded. Schema, approved owner and media catalog were restored;
production database storage and credentials were not mounted into the verifier.
