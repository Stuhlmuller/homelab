# OpenClaw Enterprise Foundation

This directory prepares dormant namespace, secret and PostgreSQL TLS boundaries.
Its Argo Application and root Terragrunt unit are declared with automatic sync
disabled; they have not been applied. `openclaw-agents` is an external
namespace reserved for one fresh OCE tenant. The upstream worker rejects a
foreign NetworkPolicy there. OCE owns its tenant policies and eventual agent claim.

The three tenant RoleBindings assume Helm release `oce` in `openclaw-system`.
Keep that release name in the declared Enterprise Application. The eight
ExternalSecrets use exact SSM parameters and `OnChange`; advance their
`generated-secret-revision` annotations during rotation. The model parameter
still contains a placeholder until the owner's protected credential workflow
runs. `occ-database` assembles separate TLS-verified URLs from the generated
alphanumeric application/migration passwords; only those two URL keys reach
their respective stock chart consumers. The planned PostgreSQL Service is
`occ-postgres` and its CA mount is `/etc/openclaw/database-ca/tls.crt`.
Do not activate the agent from this declaration.

The dedicated PostgreSQL 18.6 StatefulSet uses TLS 1.3, SCRAM, an exact Service
IP and the 10Gi `openclaw-enterprise-postgres-local` claim template. T035 must
prebind `occ-postgres-occ-postgres-0` to reviewed local storage; no node is
selected here. `occ_admin` stays on the Pod-local socket, `occ_migrator` owns
the `occ` and `drizzle` schemas and has database CREATE for upstream migrations,
`occ_app` receives only upstream migrations' per-object grants, and `occ_backup`
has read-only dump access including row-security tables. The latter credential
is mounted only by the PostgreSQL bootstrap and the future backup job.
Readiness requires the database's last-statement bootstrap marker; if first-run
SQL stops after `PG_VERSION` is written, restart remains unready and retains the
PVC. There is no automatic replay or declared repair workflow yet; keep this
foundation unsynced until recovery is reviewed. PostgreSQL password rotation
needs a declared `ALTER ROLE` path;
changing an ExternalSecret or restarting the Pod does not rerun initial
bootstrap SQL.

The separate `occ-postgres-root` certificate is retained as database recovery
material; cert-manager issues a server certificate only for the private Service
FQDN in the URL. A wrapper snapshots the projected server certificate and key
before invoking the image entrypoint on each start. A renewal first fails
readiness, then liveness restarts the container so PostgreSQL loads the new
pair. The reviewed `occ-plugin` startup bytes live at
`../openclaw-enterprise/installation.yaml`. The protected
`openclaw-enterprise-startup` workflow creates and verifies only the immutable
`occ-installation-startup-86641419e595a5c812a8c8565d5cb027` Secret after
this namespace exists and before the Enterprise Application's first sync.
The application PreSync hook checks its exact bytes and chart checksum. No raw
Secret is rendered or committed. `backup.sh` refuses an incomplete
`/recovery-material` tree: `recovery.json`, all four DB password references,
root CA key/certificate, session auth, private gateway key, bootstrap output,
journal, tenant metadata/secrets and an identity-checked agent state snapshot.
It requires `jq` and rejects a recovery marker unless `writerStopped` is true
and `claimUid` is nonempty. The future T051 capture must verify that UID against
the live claim and hold the writer fence throughout backup; the marker alone is
not a live quiescence proof. The packager requires ordinary single-link files
and discards a partial set when pre-copy, post-copy, and captured path/content
manifests differ.
T051 must supply that stopped-writer snapshot and an encrypted off-node `/backup`
mount. `backup.sh` checks that `/backup` is a mount and rejects a symlinked
archive directory before creating anything; the future Job must still prove
that the volume is the reviewed off-node destination.
The current [packager](backup.sh) stages plaintext database and recovery bytes
only on a verified local `/scratch` mount. It streams a bounded tar through
pinned age v1.3.1 into a `.tar.age.partial` file on `/backup`, rechecks the
source material, then renames completed ciphertext. The QNAP
[NFS export](../../../../docs/storage-nfs.md) uses NFSv3 `sec=sys` and maps
clients to one guest identity; an NFS claim alone is not an off-node recovery
receipt. Independently decrypt and restore the completed set before T051.
The source-only capture assembler below can stage an identity-checked tree but
leaves `continuousFenceVerified:false`. No declared live reader or coordinator,
recipient projection, approved off-node mount, protected publication receipt,
or independent restore exists. A suspended CronJob with placeholder PVCs would
have no runnable recovery path; keep T051 open until both inputs and an
independent scheduled restore are verified. Stock Agent stop clears its
active revision; the [pinned API](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/reference/agents.md#L328-L334)
requires a new deployment to resume. A scheduled backup must prove either
a consistent online capture or a journaled stop, capture and new-deployment
resume with failure recovery. The normal no-change reconcile must not
redeploy just to compensate for an incomplete backup path.
The source-only [capture assembler](../../../../scripts/ci/openclaw-enterprise-capture.py)
can stage a private local tree from two namespace-local reader archives and
before/after observations. It copies the supplied retained bootstrap and
Gateway claim trees, verifies fixed control Secrets and the pinned
[OCC Kubernetes Secret backend identity](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/apps/controller/src/drivers/secret/kubernetes/index.ts),
and leaves `continuousFenceVerified:false`. The packager must reject that
marker until a protected coordinator proves continuous writer exclusion. Reader
Jobs, exact-main dispatch, fresh observation collection and a trusted fence
receipt are still absent. It needs a private local scratch mount with free space
for both archives' uncompressed contents plus 2Gi; no hosted runner capacity is
assumed. The operator archive contains `manifest.json`, the full `journal/`
and `bootstrap/` claim copies; the tenant archive contains `manifest.json`
and the full `state/` claim copy. Each manifest binds the source SHA, exact
reader Pod UID, claim UIDs, file bytes and explicit directory paths. The
private observation input contains pre/post claim, PV, Secret and stopped-runtime
reads, plus the exact reader Pods and tenant Pod list during transfer. Archive
paths must be plain relative names without `./` prefixes. The configured
`occ-gateway-654a256bceae-root` CA Secret is produced by the stock chart;
the committed gateway CA name must match it before capture can pass.
The current reconciler validates only the first one or two revisions; it
cannot safely create a fresh revision after each scheduled backup stop.
The [pinned upstream recovery guide](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/guides/deploy/production-handoff.md#L108-L130)
provides no general OCC backup/restore command and rejects live SQLite copies
or PVC persistence as verified backups. A complete online capture needs a
separately reviewed, coordinated database/storage snapshot and restore proof.
The retained operator [journal claim](../openclaw-enterprise-operator/journal.yaml)
belongs to `openclaw-system`, while the pinned Compute Driver would create the
Agent's [gateway-state claim](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/reference/drivers/kubernetes-compute/storage-and-credentials.md#L31-L54)
in `openclaw-agents`. [PVC mounts stay in the Pod's namespace](https://kubernetes.io/docs/concepts/storage/persistent-volumes/#claims-as-volumes);
one ordinary backup Pod cannot mount both claims. Coordinate the two sources and verify
their UIDs before publishing one completed set.

The pinned [Kubernetes Secret Driver](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/reference/drivers/kubernetes-secret.md#L136-L143)
never returns value bytes through the OCC API; capture the tenant's exact
Kubernetes Secret objects through reviewed namespace-scoped access, including
the Compute Driver's [generated transport and gateway credentials](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/reference/drivers/kubernetes-compute/storage-and-credentials.md#L220-L246).

Merged [publisher PR #1684](https://github.com/Stuhlmuller/homelab/pull/1684)
declares a reserved S3 role bound to GitHub Actions OIDC; no workflow assumes
it and no apply receipt exists. It cannot authenticate a CronJob;
T051 still needs declared in-cluster credential delivery or a protected
publication stage after coordinated capture.

`restore-drill.yaml` is
deliberately outside the Kustomization; T045 must run it in isolation against
a complete set and verify the result. Its
fixed-name Job is a one-shot candidate; a declared repeat/recreate workflow is
still required before T045/T049 can accept recurring restore evidence. Its Pod
logs report only the fixed success/failure stage; raw restore details remain
inside scratch and are not emitted to cluster logs. The Job reads the completed
recovery set from a read-only mount, checks its hashes before and after restore,
rejects a marker without a stopped writer and claim UID, and keeps only the
restored database and private diagnostics in scratch. T051
must publish completed directories without further writes; any change detected
during a drill fails its final hash check. Storage
placement and 24Gi restore scratch headroom need measured admission;
private routes, applying the registration and live recovery remain gated.
Validate this dormant boundary with
`nix develop --command python3 -I scripts/ci/openclaw-enterprise-foundation-test.py`.
Run `nix develop --command python3 -I scripts/ci/openclaw-enterprise-postgres-test.py`
for the PostgreSQL 18 role, TLS, dump, and isolated restore fixture. The fixture
selects the PostgreSQL 18 binaries alongside the shell's PostgreSQL 14 default
and checks its client binaries and server major before accepting a result. It
also runs pinned upstream migration 0008 as `occ_migrator` and proves `occ_app`
can use its auth table while a new ungranted table and schema creation stay
denied.
