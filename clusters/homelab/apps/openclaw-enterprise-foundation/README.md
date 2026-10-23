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
`occ-installation-startup-980de11bbc688a33741a19c9093f613e` Secret after
this namespace exists and before the Enterprise Application's first sync.
The application PreSync hook checks its exact bytes and chart checksum. No raw
Secret is rendered or committed. `backup.sh` refuses an incomplete
`/recovery-material` tree: `recovery.json`, all four DB password references,
root CA key/certificate, session auth, private gateway key, bootstrap output,
journal, tenant metadata/secrets and an identity-checked agent state snapshot.
It requires `jq` and rejects a recovery marker unless `writerStopped` is true
and `claimUid` is nonempty. The future T051 capture must verify that UID against
the live claim and hold the writer fence throughout backup; the marker alone is
not a live quiescence proof.
T051 must supply that stopped-writer snapshot and an encrypted off-node `/backup`
mount. `restore-drill.yaml` is deliberately outside the Kustomization; T045
must run it in isolation against a complete set and verify the result. Its
fixed-name Job is a one-shot candidate; a declared repeat/recreate workflow is
still required before T045/T049 can accept recurring restore evidence. Its Pod
logs report only the fixed success/failure stage; raw restore details remain
inside scratch and are not emitted to cluster logs. The Job reads the completed
recovery set from a read-only mount, checks its hashes before and after restore,
and keeps only the restored database and private diagnostics in scratch. T051
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
