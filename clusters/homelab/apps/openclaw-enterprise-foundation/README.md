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
PostgreSQL root CA key/certificate, session auth, private gateway key, generated
gateway root and listener TLS pairs, the bootstrap PVC's
`initial-admin-password` and `initial-admin-service-key.json`, journal, tenant
metadata/secrets and a claim-identified agent state snapshot.
It requires `jq` and rejects a recovery marker unless `writerStopped` is true,
`claimNamespace` is `openclaw-agents`, `claimName` matches the OCE-owned
`gateway-state-<agent-hash>` claim, and `claimUid` is nonempty. The future T051
capture must verify those fields against the live claim and hold the writer fence
throughout backup; the marker alone is not a live quiescence proof. The packager
requires ordinary single-link files and discards a partial set when pre-copy,
post-copy, and captured path/content
manifests differ.
T051 must supply that stopped-writer snapshot and an encrypted off-node `/backup`
mount. `backup.sh` checks that `/backup` is a mount and rejects a symlinked
archive directory before creating anything; the future Job must still prove
that the volume is the reviewed off-node destination.
No declared producer assembles the identity-checked recovery tree or exposes an
encrypted off-node POSIX mount. A suspended CronJob with placeholder PVCs would
have no runnable recovery path; keep T051 open until both inputs and an
independent scheduled restore are verified. `restore-drill.yaml` is
deliberately outside the Kustomization; T045 must run it in isolation against
a complete set and verify the result. Its
fixed-name Job is a one-shot candidate; a declared repeat/recreate workflow is
still required before T045/T049 can accept recurring restore evidence. Its Pod
logs report only the fixed success/failure stage; raw restore details remain
inside scratch and are not emitted to cluster logs. The Job reads the completed
recovery set from a read-only mount, checks its hashes before and after restore,
rejects a marker without a stopped writer and identified agent claim. It keeps
only the restored database and private diagnostics in scratch. T051
must publish completed directories without further writes; any change detected
during a drill fails its final hash check. Storage
placement and 24Gi restore scratch headroom need measured admission;
private routes, applying the registration and live recovery remain gated.

The former `bootstrap/output.json` placeholder was not a producer for the
pinned chart's bootstrap PVC. The packager now requires its separate
`initial-admin-password` and `initial-admin-service-key.json` files, but no
declared capture produces them. The fresh Embedded Agent's SQLite,
sessions and workspace live on an OCE-owned `gateway-state-<agent-hash>` claim in
`openclaw-agents`; the bootstrap and operator-journal claims are in
`openclaw-system`. No source path captures these claims together with tenant
Secrets and metadata, the operator journal, or the chart-generated gateway TLS
root and listener Secrets. No declared operation proves the Agent and
control-plane writers stopped throughout capture, publishes to a verified
encrypted off-node destination, or restores the complete service in isolation.
The static `writerStopped` marker and this database-only restore fixture do not
close those gaps. T049 and T051 remain pending.
These requirements follow the pinned upstream [bootstrap Job][up-bootstrap],
[agent claim][up-agent-state], and [gateway TLS templates][up-gateway-tls].

[up-bootstrap]: https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/deploy/helm/openclaw-enterprise/templates/jobs.yaml#L130-L138
[up-agent-state]: https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/apps/controller/src/drivers/compute/kubernetes/index.ts#L12738-L12759
[up-gateway-tls]: https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/deploy/helm/openclaw-enterprise/templates/gateway-routing.yaml#L23-L54

Validate this dormant boundary with
`nix develop --command python3 -I scripts/ci/openclaw-enterprise-foundation-test.py`.
Run `nix develop --command python3 -I scripts/ci/openclaw-enterprise-postgres-test.py`
for the PostgreSQL 18 role, TLS, dump, and isolated restore fixture. The fixture
selects the PostgreSQL 18 binaries alongside the shell's PostgreSQL 14 default
and checks its client binaries and server major before accepting a result. It
also runs pinned upstream migration 0008 as `occ_migrator` and proves `occ_app`
can use its auth table while a new ungranted table and schema creation stay
denied.
