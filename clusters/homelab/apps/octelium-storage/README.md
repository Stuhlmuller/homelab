# Octelium Storage

`octelium-storage` provides the in-cluster PostgreSQL and Redis stores required
by `octops init` for the self-hosted Octelium Cluster. The stores are dedicated
to Octelium and are not shared with application data.

## Secret Contract

Terragrunt generates these SSM SecureStrings:

- `/homelab/octelium/postgres-password`
- `/homelab/octelium/redis-password`

The `octelium-storage-auth` ExternalSecret materializes the values into the
`octelium-storage` namespace. The bootstrap script reads the Kubernetes Secret,
creates a temporary Octelium bootstrap file outside git, runs `octops init`, and
then deletes the temporary file.

## Storage

PostgreSQL uses a 20Gi `nfs-default` PVC. Redis uses a 5Gi `nfs-default` PVC
with AOF enabled. The QNAP NFS export squashes ownership, so both pods run as
UID/GID 65534 like the other file-backed PostgreSQL workloads in this repo.
PostgreSQL has a 30-minute startup window, a 90-second runtime liveness window,
and a 120-second termination grace period. Readiness and liveness execute
`SELECT 1` instead of only checking that PostgreSQL accepts a socket connection,
so a query-stalled server is removed from service and restarted promptly. The
pod is pinned to `zimaboard-1`; this avoids the worst observed NFS client but
does not make QNAP NFS reliable database storage.

## PostgreSQL Backup

`octelium-postgres-backup` runs daily at 02:30 UTC. It writes
one recovery set under `logical-backups/<UTC timestamp>/` on the retained
`octelium-postgres-backup` NFS claim. Each set contains PostgreSQL globals
without role password hashes, one custom-format `octelium` database dump, and
SHA-256 checksums. The Job validates the dump with `pg_restore --list`, checks
the files before and after an atomic directory rename, and retains 14 days of
completed sets.

The nominal RPO is 24 hours; the actual RPO is the age of the newest successful
Job. The source and backup claims use the same QNAP export, so this protects
against logical database failure and supports a later storage migration, but it
does not protect against NAS loss or malicious modification. The isolated
restore drill below checks logical recoverability. A production cutover path,
independent backup, and application recovery remain separate requirements.

## Isolated PostgreSQL Restore Drill

**Activation is blocked until the process isolation gate below passes.** The
`restore-drill-candidate/` kustomization owns the candidate CronJob, declared
NetworkPolicy, and script ConfigMap. The live application does not reference
this directory, and the candidate also declares `spec.suspend: true`. Its current
image/command do not establish an enforced no-network boundary. A separate
reviewed activation change must wire the verified image digest and launcher,
pass the Talos runtime gate, then add the candidate to the live resource graph
and lift suspension. Neither rendering nor merging these candidate files starts
a drill.

`octelium-postgres-restore-drill` declares a daily 04:45 UTC schedule. The 02:30
backup can start one hour late and run for one hour, so the drill waits until 15 minutes
after that complete 04:30 window. It selects the newest atomically published
recovery set, requires a timestamp from the current UTC day and no older than
30 hours, and copies only
`globals.sql`, `octelium.dump`, and `SHA256SUMS` into disposable storage. Missing,
stale, invalid, or corrupt newest sets fail; the drill never falls back to an
older backup or changes the source. A valid previous-day set cannot count as
today's successful drill.

After verifying the exact checksum manifest and archive listing, it initializes
PostgreSQL 14.23, restores role globals, and uses
`pg_restore --create --exit-on-error --dbname=postgres` to recreate the archived
database's encoding, `LC_COLLATE`, `LC_CTYPE`, and owner before restoring objects.
The C locale initializes only the disposable bootstrap cluster. PostgreSQL's
custom archive already retains database metadata; the backup does not need a
new `pg_dump --create` option. Missing locale support fails the drill instead
of substituting C. See [PG14 dump options](https://www.postgresql.org/docs/14/app-pgdump.html)
and [restore options](https://www.postgresql.org/docs/14/app-pgrestore.html).
The real PG14 fixture uses `en_US.UTF-8` and compares restored database metadata
with its source; Linux Nix shells include the locale archive. The drill then
requires all three deployed Core/Enterprise resource and wrapped-key tables to
contain rows, normal resource JSON UIDs to match their row identities, encrypted
resources to reference present nonempty wrapped keys, and application indexes
to be valid. These checks exercise the database backup, including the encrypted
recovery set, without printing resource contents or key material.

The Pod has no production database volume, injected production credentials,
Kubernetes Secret mount, or service-account token. The backup itself contains
sensitive database material. Its only PVC is the backup claim, read-only at both
the volume and mount. PostgreSQL's empty `listen_addresses` disables its TCP
listener; it does not restrict outbound connections or other processes.
PostgreSQL uses a private Unix socket and a size-limited `2Gi` disk `emptyDir`;
the Job has a 30-minute deadline and bounded CPU, memory,
and ephemeral storage. Restored data and private diagnostics disappear when the
Pod is deleted; finished Jobs expire after one hour. The retained source archive
continues to follow its existing 14-day policy.

NetworkPolicies are additive: the former namespace-wide Octelium ingress rule
now selects only the existing PostgreSQL and Redis server labels. Their Services
and allowed ingress are unchanged. Backup Jobs initiate connections and need no
inbound rule. A namespace-wide ingress default deny and the drill's separate
ingress/egress deny policy declare the intended boundary. The current Flannel
deployment does not enforce these policies; see
[`docs/runtime-isolation.md`](../../../../docs/runtime-isolation.md).
These manifests and their tests prove declared policy and storage contracts only,
not network isolation. No broader allow policy may select the drill once policy
enforcement is available. Read-only NFS volume access is performed by the node
mount, outside Pod network traffic.

Before activation or loading real backup material, implement a reviewed,
actually enforced no-network process boundary covering the restore client,
PostgreSQL, and every child process from before archive processing starts.
Restore input can cause arbitrary code execution; checksums and a Unix-only
database listener do not contain it. See the
[PostgreSQL restore warning](https://www.postgresql.org/docs/14/app-pgrestore.html).
Negative-test the exact launcher, image, UID, and security profile with synthetic
archives: direct IPv4/IPv6 and DNS attempts to Pod, Service, node/LAN, and public
destinations must be denied, including attempts from archive-triggered child
processes. Verify actual enforcement rather than treating unreachable test
endpoints as proof, and require the local Unix-socket restore to pass. The
boundary must fail closed if it cannot be installed and must persist through
the entire drill. Record that evidence before approving activation; the present
manifest test and successful local fixtures do not satisfy this gate.

The shared Grafana backup-staleness alert also requires a successful drill within
30 hours, including a CronJob that has never succeeded. Validate the reviewed
change before merge:

```sh
nix develop --command python3 scripts/ci/octelium-restore-drill-test.py
nix develop --command bash scripts/ci/static-checks.sh
kubectl kustomize clusters/homelab/apps/octelium-storage
kubectl kustomize clusters/homelab/apps/octelium-storage/restore-drill-candidate
```

Only after the enforced isolation gate passes and the activation change is
reviewed, use normal Argo CD rollout and wait for the scheduled run; do not create
an ad hoc Job or modify live state. Check:

```sh
kubectl -n octelium-storage get cronjob octelium-postgres-restore-drill \
  -o jsonpath='{.status.lastSuccessfulTime}{"\n"}'
kubectl -n octelium-storage get jobs \
  -l app.kubernetes.io/name=octelium-postgres-restore-drill
kubectl -n octelium-storage get job <scheduled-restore-drill-job> \
  -o jsonpath='{.status.conditions}{"\n"}'
```

Completion is reported by the Job's exit status and conditions. The restore
process permanently redirects standard streams to private scratch before archive
processing; successful and failed restores both leave container logs empty.
Do not save console descriptors for a summary or add a shell supervisor that
retains them: archive-triggered client and server programs could inherit or reopen
those handles through `/proc`. Run the script directly as the container entry
point (or through an `exec`-only isolation launcher), with its own PID namespace.
Do not enable `hostPID` or `shareProcessNamespace`.

The result, failure stage, and private details remain in
`/work/restore-drill/details.log` only until Job cleanup. Inspect them privately
if needed; never copy them into public
CI logs, issues, or PRs. Fix archive format/schema changes in code, and increase
scratch limits only after checking node capacity. No live success is claimed
until a scheduled Job completes.

This drill does not connect Octelium to the restored database, decrypt resources
with external encryption keys, exercise production cutover, restore Redis or
Enterprise package-store PVCs, or protect against NAS loss. It proves the named
PostgreSQL recovery set can be restored and passes these explicit invariants.
Keep external encryption-key recovery material and the existing backup target.

After activation, to stop future runs, commit `spec.suspend: true` to this CronJob and let Argo CD
sync it. Suspension leaves an already running drill to finish within its deadline.
For full removal, revert the drill resources, ConfigMap, and alert expansion
through a reviewed PR; preserve the backup CronJob and claim. No production data
rollback is needed because the drill never writes there.

## Validation

```sh
kubectl -n octelium-storage get externalsecret,secret octelium-storage-auth
kubectl -n octelium-storage get statefulset,cronjob,pod,pvc,svc
kubectl -n octelium-storage exec statefulset/octelium-postgres -- psql -U octelium -d octelium -Atqc 'SELECT 1'
kubectl -n octelium-storage exec statefulset/octelium-redis -- redis-cli ping
kubectl -n octelium-storage get cronjob octelium-postgres-backup -o jsonpath='{.status.lastSuccessfulTime}{"\n"}'
kubectl -n octelium-storage get job -l app.kubernetes.io/name=octelium-postgres-backup
kubectl -n octelium-storage logs job/<latest-octelium-postgres-backup-job>
```

Redis requires authentication for real clients; the unauthenticated `PING` can
return `NOAUTH` while still proving the TCP listener is reachable.
