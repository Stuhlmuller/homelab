# Harbor private OCI registry

Harbor hosts the homelab's private container images and OCI artifacts at
`https://harbor.stinkyboi.com`. The upstream [Helm chart 1.19.2][chart-release]
deploys Harbor **2.15.2** through the repository's Argo CD Application. Chart
images and the separate PostgreSQL **18.6** image are pinned by digest.

## Access and authentication

The public hostname uses the existing Cloudflare Tunnel, an anonymous Octelium
WEB transport, then the private Istio gateway. Harbor authenticates browsers
and OCI clients itself. The transport must preserve `Authorization` and the
OCI bearer-token challenge; a browser SSO redirect would break containerd,
Docker, Helm, and ORAS. Internal publisher Pods use the same HTTPS hostname
through CoreDNS split resolution to the existing Istio gateway.

Public Tunnel requests remain subject to Cloudflare's [upload limits][limits].
Large-image migration and publication use the CI TLS port-forward into Istio. A
successful browser page or `/v2/` challenge does not prove large uploads.
Talos containerd resolves names through the host resolver, so the Pod-only
CoreDNS rewrite does not change node image pulls. Verify a new Pod can pull a
private digest before changing a workload's image source.

The chart's nginx Service is ClusterIP on port 80. Istio terminates the trusted
wildcard HTTPS certificate; nginx returns relative upload locations and the
VirtualService does not retry writes or impose a streaming timeout. Network
policies allow the gateway to nginx, Harbor components to their peers, the
bootstrap Job to the API, and monitoring to metrics. PostgreSQL accepts only
Harbor core/exporter and its backup Job. The namespace does not opt into Istio
ambient until that additional traffic path is validated.

Self-registration is disabled and only administrators can create projects.
The PostSync bootstrap creates the private `homelab` project and reconciles:

| Robot | Permissions | Use |
| --- | --- | --- |
| `robot$homelab+pull` | Pull repository | Kubernetes `imagePullSecrets` |
| `robot$homelab+publisher` | Pull/push repository | Protected image publishing and migration |

Bootstrap and Harbor's own images stay on upstream registries to avoid a
recovery dependency on the service being recovered. Keep original migration
sources until independent pulls and workload rollouts succeed. Do not delete
old GHCR artifacts as part of migration.

## Image scanning

Trivy is enabled in `values.yaml`, with a retained 5 Gi database/cache PVC.
The PostSync bootstrap reconciles `homelab` project metadata `auto_scan: "true"`
so newly pushed images receive vulnerability scans. It verifies the setting
on readback and repairs drift on subsequent syncs. Existing artifacts are not
retroactively scanned by enabling scan-on-push.

After rollout, verify the Trivy Pod is Ready and a newly pushed image shows a
completed vulnerability report in Harbor. Bootstrap success proves the project
setting, not successful database downloads or an image scan.

## Local image signing

The protected NOFX publisher creates `signing-job.yaml` for two verified image
digests. This template is deliberately excluded from Kustomize: it runs once
per publication. cert-manager owns the separate `harbor-image-signing` P-256
key Secret, with `rotationPolicy: Never`. The key stays inside the cluster;
only its public key returns to CI for verification. Signatures remain private
in Harbor. See [the signing and recovery runbook](../../../../builds/nofx/README.md#private-image-signing).

The signing NetworkPolicy records desired egress only: the current flannel CNI
does not enforce it. Compromised signing code could exfiltrate its mounted key
and publisher credential; Harbor is not mesh-enrolled. The runbook and knowledge
base track the enforcing-dataplane and denied-egress acceptance work.

## Secrets and reconciliation

`harbor-secrets` is an `OnChange` ExternalSecret backed by these generated
`/homelab/harbor/` SSM parameter suffixes:

| Suffix | Contract |
| --- | --- |
| `admin-password` | Initial `admin` credential and bootstrap API authentication |
| `secret-key` | Exactly 16 characters; encrypts persisted Harbor credentials |
| `core-secret` | Exactly 16 characters; internal core authentication |
| `xsrf-key` | Exactly 32 characters; browser CSRF key |
| `jobservice-secret` | Exactly 16 characters; internal job authentication |
| `registry-http-secret` | Exactly 16 characters; upload-state authentication |
| `registry-password` | Internal registry controller credential; ESO renders bcrypt htpasswd |
| `database-password` | PostgreSQL password; `password` is the chart-required key alias |
| `robot-pull-password` | Project pull robot credential |
| `robot-push-password` | Project publisher robot credential |

The chart uses stable secret references instead of Helm-generated random
credentials. cert-manager owns the RSA token-signing certificate and key in
`harbor-token-signing`; the local self-signed issuer serves internal token
signing only, not client-facing HTTPS. Its ten-year certificate and
`rotationPolicy: Never` preserve the signing key during ordinary GitOps
reconciliation. Before certificate renewal, plan a repository-owned restart of
core and registry so both load the renewed certificate; verify token issuance
and a private image pull afterward.

Harbor's chart requires secret-backed environment references for some
components. Secret values are not committed. PostgreSQL and bootstrap consume
mounted files; publisher credentials never belong in workload environment
variables or Dockerfiles. Changing SSM alone does not rotate the PostgreSQL
role or an existing Harbor admin account. Coordinate their API/SQL rotation
through a reviewed repository-owned workflow and verify dependent consumers.
Never replace `secret-key` without a supported migration of encrypted data.

The chart's internal cache is Valkey, exposed through the historical `redis`
values. It has no chart-supported password option; port 6379 is reachable only
from Harbor-labeled Pods in this namespace. Do not grant untrusted workloads
permission to run in the Harbor namespace.

## Storage and backups

| Claim | Size | Storage | Recovery contract |
| --- | --- | --- | --- |
| `harbor-registry` | 50 Gi | Retained `nfs-default` | Authoritative image layers/manifests; preserve with database |
| `harbor-postgres-local` | 10 Gi | Retained static local PV on `acer` | Metadata, users, projects and jobs; nightly logical backup |
| `harbor-postgres-backup` | 10 Gi | Retained `nfs-default` | Fourteen days of verified PostgreSQL dumps |
| `harbor-redis` | 1 Gi | Retained `nfs-default` | Cache and pending job state |
| `harbor-jobservice` | 1 Gi | Retained `nfs-default` | Job logs |
| `harbor-trivy` | 5 Gi | Retained `nfs-default` | Re-downloadable scanner databases/cache |

The database PV uses `/var/lib/harbor-postgres` on `acer` rather than the QNAP
NFS path because existing database workloads have suffered NFS stalls. It is
not replicated and a Talos ephemeral-partition reset or control-plane disk
loss removes it. The 10 Gi capacity is a scheduling claim, not a hostPath disk
quota. Monitor the node's free space and migrate through a reviewed storage
change before exhaustion. NFS capacity requests likewise do not reserve or
limit QNAP subdirectory usage.

`harbor-postgres-backup` runs daily at **03:35 America/Los_Angeles**. It writes
`globals.sql` without password hashes, a custom-format `registry.dump`, and
SHA-256 checksums into a private partial directory. It validates the archive
with `pg_restore --list`, verifies checksums, then renames it into
`logical-backups/<UTC timestamp>`. Only completed snapshots older than fourteen
days and stale partial directories are removed. A failed job cannot prune the
last successful archive. Readiness probes exercise a database query; startup
allows thirty minutes for crash recovery and shutdown allows two minutes.
Container recovery can span Argo CD's separate fifteen-minute sync timeout;
the probe window does not extend one sync operation.
The PostSync `harbor-postgres-backup-initial` Job has a ten-minute deadline,
within that operation timeout, and uses the same `backup.sh`
ConfigMap after bootstrap, proving a verified dump during every successful
rollout without an ad hoc Job creation. Argo CD retains a failed hook for
inspection and replaces it on the next sync.

The nightly dump is a **metadata backup**, not a complete registry backup or a
restore drill. The registry blobs and database backup share the QNAP failure
domain. Retention does not protect against NAS loss. Before retiring original
package sources, arrange an independent backup of registry blobs, database
dumps and the SSM secret contract, and test restoring into an isolated Harbor
instance. Cache/job-log claims do not replace these artifacts.

### Restore and rollback

1. Keep the original package registry available while bootstrapping recovery.
   Pause publishers through their declared workflows; put Harbor into read-only
   mode through a reviewed API reconciliation before taking a coordinated
   registry snapshot and database dump.
2. Verify dump checksums and `pg_restore --list`. Restore the matching retained
   registry snapshot and database into isolated replacement PVCs through a
   reviewed GitOps recovery overlay. Restore SSM references and the encryption
   key before starting Harbor. PostgreSQL 18 is required for this dump path;
   the declarative `harbor` database role must use the mounted SSM password.
3. Use an isolated recovery Job to run `pg_restore --clean --if-exists
   --no-owner --dbname=<replacement-database> registry.dump` against the
   replacement database. Run it only against the explicitly declared recovery
   target, then verify project privacy, robot authentication and artifact
   digests before switching the Service to the restored database.
4. For an application rollback, revert GitOps values and package references in
   a reviewed PR. Preserve all claims. Do not downgrade a PostgreSQL data
   directory or Harbor schema in place; restore matching versions and backups.

This app does not yet contain an automated full restore overlay. That is a
separate required code path before performing destructive recovery. Upstream
[Harbor 2.15.2 release notes][harbor-release] call out its bundled PostgreSQL
major upgrade; this deployment uses a separately managed PostgreSQL workload
so future chart changes cannot silently upgrade its database engine.

## Validation

```sh
nix develop --command bash scripts/ci/harbor-check.sh
kubectl kustomize clusters/homelab/apps/harbor
kubectl -n harbor get pods,pvc,externalsecret,certificate
kubectl -n harbor get jobs -l app.kubernetes.io/component=bootstrap
kubectl -n harbor get cronjob harbor-postgres-backup
curl -sS -D - -o /dev/null https://harbor.stinkyboi.com/v2/
```

Expected unauthenticated `/v2/`: `401` and a Harbor bearer challenge, without
an Octelium login redirect. Validate an unauthorized private artifact pull is
denied, a robot-authenticated pull succeeds, a >100 MiB artifact round trip
works through the in-cluster path, migrated manifest digests match, and a new
Kubernetes Pod pulls the private digest. Check the first completed database
backup and the ServiceMonitor target; do not infer success from manifest
rendering or an Argo CD sync alone.

[chart-release]: https://github.com/goharbor/harbor-helm/releases/tag/v1.19.2
[harbor-release]: https://github.com/goharbor/harbor/releases/tag/v2.15.2
[limits]: https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/
