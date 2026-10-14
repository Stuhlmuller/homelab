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
readiness. Neither has been applied yet. The website and account identities both use `mastodon.stinkyboi.com`. This
preserves the private apex portal and makes federation discovery independent
of private apex DNS. The default administrator is `rodman`, using the existing
repository owner address `rodman@stuhlmuller.net`. No account has been created. Google Workspace SMTP defaults use `smtp.gmail.com:587`, the existing owner
login, and that same sender address. Its protected password is still a
placeholder; the Rails launcher rejects activation until it is injected.

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
streaming runs separately on port 4000. Schema preparation runs in wave 1, owner bootstrap in wave 2, and the
Deployments start in wave 3. Web and Sidekiq mount the retained media
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
  the final receipt after the Ruby prerequisite.
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
revert the Application/workload change through protected `main`; retained PVs,
PVCs, SSM keys, and backups must remain available for recovery.
