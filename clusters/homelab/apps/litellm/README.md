# LiteLLM gateway

LiteLLM is the internal OpenAI-compatible gateway for OpenClaw, Multica, n8n
and NOFX. It exposes only `openrouter/free`.

The existing `/homelab/litellm/openai-api-key` SSM SecureString is the
OpenRouter upstream credential for this gateway. Its legacy name is retained to
avoid a secret-path migration. It seeds the encrypted UI credential once and
remains mounted only in LiteLLM for initial bootstrap; callers authenticate
with separate inference-only keys:

- `/homelab/openclaw/litellm-app-token`
- `/homelab/multica/litellm-token`
- `/homelab/nofx/litellm-token`
- `/homelab/n8n/litellm-token`

The guarded ASGI entrypoint rejects caller-controlled provider credentials,
routing and telemetry before native authentication. It rejects callbacks
and telemetry configuration; injects the upstream credential only in memory;
and emits trusted caller attribution to Langfuse. Raw request logging is
disabled. The Langfuse keys are mounted only in LiteLLM.

## Validation and rollout

### Gateway runtime controls

The gateway uses `RuntimeDefault` seccomp, disables privilege escalation and
drops all Linux capabilities. Its dedicated ServiceAccount remains tokenless.
Run `python3 -I scripts/ci/litellm-runtime-hardening-check.py` in the pinned
Nix shell to lint and render the declared chart and verify these controls.
The check uses anonymous public chart access and fails if the chart declaration
changes without updating its fixture.

After Argo observes the merged revision, verify the live Pod controls,
readiness and restart count, native database startup, and authenticated calls
from each active consumer. Keep #844 open through its 24-hour acceptance
window. Do not start retired consumers for this check. Nonroot execution and
a read-only root filesystem need a separate writable-path rehearsal against
the current native database startup. Roll back through a reviewed values
revert if these controls prevent startup or normal inference.

### Gateway memory reservation and executable rollout gate

The gateway values reserve `1Gi` memory and select `kubernetes.io/hostname:
acer`. This is staged prevention for #775/#793, not restored capacity or an
instruction to recover a worker. The protected PR pipeline checks sustainable
rollout headroom before merge. The gateway keeps one replica and the
chart's default RollingUpdate strategy: one surge Pod, zero unavailable Pods.
Its image, runtime controls, database and caller routes are unchanged.

On November 2, overlapping unreserved gateway Pods on the 1.28 GiB allocatable
worker coincided with severe memory pressure and a stalled kubelet. Their
combined cgroup memory was about 869 MiB; the old gateway's recorded peak was
800.5 MiB. The replacement on Acer used 479–539 MiB and became Ready without
restarts. This supports a 1 GiB reservation and avoiding the small worker; it
does not prove OOM or establish a maximum under all inference loads. No hard
memory limit is added without that evidence. Other workers were already using
82–84% of allocatable memory, so exclusion of only the smallest worker would
allow an unsafe relocation. Acer-only placement is a temporary capacity
constraint, not high availability or a completed failure-domain target.

The 03:03 UTC snapshot left Acer 1,806.7 MiB unreserved and approximately
2,391.7 MiB below allocatable actual usage. The first new 1 GiB Pod fits because
the existing gateway has no request. After replacement, only 782.7 MiB would
remain unreserved: a later surge could stay Pending. At least 241.3 MiB of
additional reservations must be freed to fit two reserved Pods at that snapshot;
this is arithmetic, not a safety margin or durable capacity receipt. Do not
lower the request or move the gateway to a pressured worker to force rollout.
[PR #1656](https://github.com/Stuhlmuller/homelab/pull/1656) changes native
PostgreSQL placement and other workloads, not gateway placement. Coordinate
its Cordium capacity assumptions with this new reservation; do not apply its
held changes or count projected savings as available capacity.

The apparent 512 MiB gain at 03:16 UTC came from the hourly Renovate Job
finishing at 03:04:56 UTC. Its unsuspended Acer-only CronJob still reserves
512 MiB each run. Budget recurring reservations even between runs: do not
ignore future demand because a snapshot omits completed Jobs. Other unsuspended
Acer-eligible jobs add 448 MiB: Mastodon restore verification (128 MiB), media
PostgreSQL backup (64 MiB), Fleet MySQL backup (128 MiB), Harbor PostgreSQL
backup (64 MiB), and Octelium PostgreSQL backup (64 MiB). The last three are
unpinned and can land on Acer. Their schedules differ, but overlap cannot be
excluded without verified durations. Conservatively reserve 960 MiB for all
six when absent. For a future 1-GiB-to-1-GiB rollout, the earlier 241.3 MiB
deficit is only the Renovate-inclusive minimum; the full conservative deficit
at the job-free snapshot is 689.3 MiB. These deficits concern that future
two-reserved-Pod state, not the initial transition from the unreserved Pod.
Terminal Pods were already excluded from accounting; deleting them adds no room.
Fresh seven-day telemetry also invalidates PR #1656's old Dispatcharr Celery
assumption: observed peak 666.72 MiB exceeds both its current 512 MiB request
and the proposed 448 MiB. Do not count that reduction. ClickHouse and Langfuse
worker also exceeded their requests. Smaller candidate reductions remain
unverified because startup/recovery samples are absent and scrape availability
was only about 76%; instantaneous free memory does not justify them.

The read-only `scripts/ci/litellm-release-check.py` runs after CI installs its
existing kubeconfig, before the live Terragrunt plan. The aggregate
`Terragrunt Gate` fails on an unhealthy target, stale/incomplete evidence,
unclassified recurring overlap or insufficient reservation/actual memory.
It counts every eligible unsuspended CronJob conservatively, deducts only
already counted active owned Job Pods, and retains terminating Pod requests.
It reuses the existing Kubernetes request calculator for init sidecars,
Pod-level resources and overhead; unresolved resize or pending placement fails.
Scheduler accounting reserves the serving Pod's actual effective request plus
the new Pod's 1 GiB request. RollingUpdate retains the old revision's resources:
the initial unreserved-to-1-GiB transition needs 1 GiB, while later 1-GiB-to-1-GiB
rollouts need 2 GiB, in addition to other Pods and recurring reservations.
The physical check still requires fresh kubelet Summary available bytes for a
2 GiB gateway envelope plus absent recurring demand, minus the exact serving
Pod's already consumed working set (at most 1 GiB). This is a sampled physical
margin, not a hard memory bound: neither gateway revision has a memory limit.
Node/Pod metrics must be fresh and collected within 30 seconds of each other.
API denial fails closed; this change grants no new access and prints no private
metrics. The check covers this rollout's scheduler budget and sampled memory
margin; it does not prove the wider #793 failure-domain target.

For diagnosis and post-merge acceptance:

1. Recheck node conditions, `kubectl top nodes`, and the actual gateway memory
   and readiness with `kubectl -n ai top pod -l app.kubernetes.io/name=litellm
   --containers` and `kubectl -n ai get pods -l app.kubernetes.io/name=litellm
   -o wide`. Keep #844's native startup, caller and 24-hour acceptance gates.
2. Recompute Acer scheduling requests from all nonterminal bound Pods,
   including terminating Pods, restartable init containers and Pod overhead.
   Require room for **both** 1 GiB gateway Pods: at least 2 GiB unreserved while
   the old gateway has no request; after correction, at least 1 GiB unreserved
   in addition to the running gateway. Inventory every unsuspended CronJob
   eligible for Acer, including unpinned templates; account for verified run
   durations and overlap, or conservatively include all of them. With all six
   current jobs absent, reserve another 960 MiB: require 3,008 MiB unreserved
   before correction, or 1,984 MiB after one corrected gateway is running.
   Subtract reservations already counted for their active owned Job Pods to
   avoid double-counting. The Renovate-only 2.5 GiB/1.5 GiB thresholds are
   insufficient for this full inventory. Require actual memory margin for the
   additional measured startup peak and system/workload growth, with no active
   pressure. A `top` snapshot alone is not a capacity proof. Keep raw evidence private; unavailable evidence fails the executable gate.
3. Run `python3 -I scripts/ci/litellm-runtime-hardening-check.py` in the pinned
   Nix shell, then normal policy/PR checks. The actual declared chart render
   checks the reservation, placement, strategy and security controls with
   negative regressions; it does not certify live capacity.
4. After reviewed delivery, require Argo's exact revision, Synced/Healthy,
   a new Ready gateway Pod on Acer with `1Gi` requested memory, stable restart
   counts and pressure, native PostgreSQL/caller behavior, and renewed surge
   headroom. Keep #775/#793/#785 open until their wider acceptance is met.

Existing processes on the stalled worker need separate repository-owned
recovery and fencing checks. Desired placement does not stop an already bound
Pod. Do not delete Pods, drain, reboot, or reuse dated recovery exceptions as
part of this proposal. Preserve PostgreSQL data and out-of-band access.
If the new Pod stays Pending, retain the serving old Pod and resolve capacity
through reviewed source changes. Roll back only this proposal through a
reviewed values revert after reassessing placement and memory; reverting also
restores the old unreserved-placement risk, so it is not a node recovery tool.

### October 10, 2026 native-key rollout

[PR #1243](https://github.com/Stuhlmuller/homelab/pull/1243) merged as
`998041ea` after all protected checks passed. Argo observed that revision with
Synced/Healthy and a successful operation. The new gateway pod became Ready
without restarts; PostgreSQL contains the native schema, import marker and four
service-key rows. The native UI key-list API returns `openclaw`, `multica`,
`nofx` and `n8n`. Each caller's own running pod authenticated to
`http://litellm.ai.svc.cluster.local:4000/v1/models` with its configured key and
received only `openrouter/free`.

A disposable ten-minute key passed creation, authentication, block, unblock
and deletion checks through the native API. Block and delete invalidated its
warm authentication cache. The test key was deleted; service keys were not
modified. Langfuse's repaired Valkey AOF loaded after the reviewed restart on
October 10. Fresh bounded requests using each of the four mounted service keys
produced attributed Langfuse `GENERATION`s through `openrouter/free`, with
input/output and nonzero usage. The n8n key's first free-model response had no
assistant text; a second returned `READY` and was traced. Browser UI rendering,
native post-recovery caller actions, and a database restore drill remain
unverified. Model discovery alone is not completion.

### Native database-backed service keys

The dedicated `litellm-postgres` StatefulSet stores UI-visible virtual keys.
The gateway reads its nonsuperuser database password from a mounted file and
creates a private temporary native config before CLI initialization. Native
LiteLLM applies its pinned schema migrations. Before accepting HTTP traffic,
`native_keys.py` imports the four existing SSM caller values as hashed native
keys and creates their internal-user records in one locked transaction.
Clients need no key rotation. Each key permits only model discovery and free
chat completions, including both versioned and unversioned paths.

The `homelab-native-key-import-v1` user record marks completed import in the
same transaction. Once present, startup never recreates keys or restores old
permissions. UI deletion, blocking and rotation remain authoritative across
restarts. Do not delete this marker. An existing user/key collision aborts
startup rather than overwriting operator state. No custom-auth hook remains:
the native database verifier authorizes requests, while ASGI admission blocks
provider and telemetry overrides before native error logging can parse them.
Only the trusted pre-call hook inserts the database-backed upstream credential.
Telemetry admission covers management and model-discovery routes too: native
authentication failures can parse their bodies before logging. Model/provider
restrictions apply only to inference, preserving native key-management bodies.

The image pin selects the Linux amd64 child of the upstream OCI index because
Harbor 2.15.2 rejects that index's repeated child descriptors. All four observed
nodes were amd64 on October 19, 2026. The exact child passed the protected
[Harbor publication and full-pull receipt](../../../../docs/harbor-image-mirroring.md#duplicate-index-publication-failure)
before this consumer changed. Re-evaluate the pin before adding arm64 nodes;
the full-catalog mirror receipt remains pending.

The pinned image is affected by
[GHSA-4xpc-pv4p-pm3w](https://github.com/BerriAI/litellm/security/advisories/GHSA-4xpc-pv4p-pm3w).
Admission rejects malformed or duplicate Host headers on every HTTP route
before native authentication, including direct ClusterIP access. Tests pin the
deployed FastAPI/Starlette versions: the unguarded management route reproduces
the bypass and the guarded route rejects it. Keep this mitigation until an
image upgrade and its regression tests establish the upstream fix; a newer
implicit test dependency is not evidence that the deployed image is safe.

SSM provides initial caller material, not a continuous key reconciliation
loop. After import, changing SSM alone does not rotate a database key. Coordinate
any later UI/API rotation with that caller's SSM value and refresh contract.

### UI-managed OpenRouter credential

`native_keys.py` imports the existing OpenRouter value into native
`LiteLLM_CredentialsTable` as `openrouter`, encrypted with LiteLLM's native
encryption helper. Its independent `homelab-provider-credential-import-v1`
marker commits in the same locked transaction. Existing credential collisions
abort startup; completed imports never overwrite UI edits or recreate deletion.
The four caller keys stay under **Virtual Keys**; OpenRouter appears under
**Models → LLM Credentials**. The bootstrap master key and PostgreSQL/Langfuse
credentials retain their separate administrative and infrastructure roles.

The pre-call hook reads and decrypts only this row's `api_key` on each request.
UI replacement/deletion affects subsequent requests without restarting; missing,
invalid or unreadable credentials return 503 with no mounted-secret fallback.
Inference admission also rejects `litellm_credential_name` overrides. Native
`store_model_in_db` enables the UI credential loader and its 30-second refresh;
the gateway loads credentials again after first import, before serving traffic.
`supported_db_objects: []` keeps models and other routing objects in Git.
The inference model remains restricted to `openrouter/free`.

After migration, change the provider credential in the UI/API. Updating SSM
alone no longer rotates the active provider key. Keep SSM as bootstrap/recovery
material and preserve the database plus import markers. The existing master key
is the native encryption key because no separate salt is configured: retain it
with database backups, and do not rotate it without re-encrypting stored values.
Never return to file-backed inference during rollback; restore the database.

Pinned 1.80.8 UI limitation: editing a credential preloads a masked value. Enter
the complete replacement key before saving; saving that mask can overwrite the
credential. Review the upstream credential edit flow during the next image
upgrade. Native stdout/client errors also remain outside the existing Langfuse
redaction guarantee; see the [AI observability findings](../../../../openwiki/architecture/ai-observability.md).

Before rollout, capture a private logical backup. After rollout, require the
`openrouter` entry from `/credentials`, one encrypted database row, unchanged
caller aliases, and a bounded real generation. Local database tests cover
encryption, concurrent import, collision rollback, UI rotation/deletion,
restart preservation and unavailable-credential failure without using live keys.

PostgreSQL reuses the mirrored PostgreSQL 14 image and a 20 GiB `nfs-default`
claim, `data-litellm-postgres-0`. Generated SSM credentials are
`/homelab/litellm/postgres-admin-password` and
`/homelab/litellm/postgres-app-password`. Only PostgreSQL receives the admin
password; `litellm-postgres-client` contains only the app password. The init
script creates the nonsuperuser `litellm` role and owned database on an empty
volume. Network and Istio policies admit port 5432 only from LiteLLM.
Both policies use sync wave `-1`, before PostgreSQL's wave `0`: unavailable
Istio admission must block initial database deployment, not leave policy
installation racing the database startup.

PR #1230 merged as `201e0988`. Its reviewed SSM plan was applied and the
database reached Ready with a Bound PVC and both ExternalSecrets Ready.
On October 10, 2026, the Istio webhook outage exhausted Argo's retries before
the database AuthorizationPolicy was created. The worker and `istiod` later
recovered; this ordering correction supplies a new reviewed revision for
normal automatic reconciliation. Require Synced/Healthy, a successful sync,
and the policy present before native-key migration. Do not bypass admission.

The Application enables
[server-side diff](https://argo-cd.readthedocs.io/en/stable/user-guide/diff-strategies/)
through `IaC/homelab/us-west-2/apps/litellm/stack.hcl`. Argo's older structured-merge comparison
reported the Ready PostgreSQL StatefulSet OutOfSync while both the normal CLI
diff and Kubernetes server-side dry run were empty (including Argo tracking
metadata). This setting uses admission-aware dry runs without ignoring fields
or changing database resources. Apply the reviewed registration with the
targeted `litellm` Terragrunt workflow; require actual Synced/Healthy afterward.

On October 10, 2026, PR #1244 merged as `058fec59`; targeted apply
[38082662328](https://github.com/Stuhlmuller/homelab/actions/runs/38082662328)
succeeded and the live Application has `ServerSideDiff=true`. PostgreSQL and
its PVC/secrets remain Ready/Bound. The first post-apply comparison still
reported the previous OutOfSync result.
[Argo 3.4.2 cache selection](https://github.com/argoproj/argo-cd/blob/v3.4.2/controller/state.go#L1036-L1072)
does not invalidate cached diffs for this metadata-only change, and server-side
diff keeps that cache across ordinary status expiration. A new source revision
invalidates it. Verify the next observed Git revision and fresh Synced/Healthy
result before the native-key cutover; do not treat successful apply alone as
convergence or bypass it with an ignored-field rule.

Provision these parameters and exact reader grants through the reviewed shared
SSM Terragrunt unit before acceptance. Require both ExternalSecrets Ready, the
claim Bound, StatefulSet Ready and `SELECT 1` as the app role. Passwords are
file-backed. SSM rotation alone does not change an initialized PostgreSQL role;
use a reviewed role-password migration before changing mounts.

Before schema upgrades or auth cutover, keep a private logical `pg_dump` of
database `litellm` alongside its NFS snapshot and SSM recovery material. Restore
the database before restoring database-backed authentication; retain its PVC
during rollback. Returning to file-backed authentication would ignore UI
revocations and must not be an automatic recovery action.

Validate with `scripts/ci/litellm-postgres-check.py`, the pinned SDK
`litellm-attribution-check.py` and `litellm-native-auth-test.py`, plus
`litellm-native-database-test.py` under the Nix shell with the generated Prisma
0.11.0 client. The database test uses isolated local PostgreSQL, the pinned
native migrations, and a nonsuperuser owner. It proves atomic concurrent import,
rollback on collision, and preservation of deleted/blocked keys after restart.
CI runs these without production credentials.

Before rollout, take the private logical backup described above and verify the
database policies, Ready Secret/PVC and app-role connection. After rollout,
require four aliases (`openclaw`, `multica`, `nofx`, `n8n`) in the UI and test a
separate disposable key through UI/API create, authenticate, block and delete.
Prove cache invalidation and restart preservation, then each native caller's
inference and correlated Langfuse generation. Local fixtures do not prove these
live acceptance gates. Never roll back to file-only authentication: that would
silently ignore database revocations. Preserve the database and import marker.

Run:

```sh
nix develop --command python3 -I scripts/ci/langfuse-staging-check.py
nix develop --command python3 -I scripts/ci/litellm-attribution-check.py
kubectl kustomize clusters/homelab/apps/litellm
```

Before acceptance, make one bounded generation per migrated caller and verify a
correlated Langfuse generation has the caller identity, `openrouter/free`,
input/output and nonzero provider usage. Gateway health and a Ready
ExternalSecret are not acceptance evidence.

NOFX uses a separately pinned image containing
`builds/nofx/patches/0013-litellm-runtime-routing.patch` and mounts its gateway
route and dedicated token only in the backend.

Sources: [LiteLLM custom authentication](https://docs.litellm.ai/docs/proxy/custom_auth),
[Langfuse LiteLLM integration](https://langfuse.com/integrations/gateways/litellm).
