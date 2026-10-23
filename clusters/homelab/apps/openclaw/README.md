# OpenClaw

## Enterprise replacement retention

This shutdown stage sets the legacy gateway to zero replicas and suspends its
runtime-backup CronJob. Apply it only after the protected inventory confirms
the reader is Ready, all four retained PVC/PV identities are bound and the
off-NAS archive destination is available. The reader remains one read-only Pod
on the legacy node. Existing PVCs carry `Prune=false`, local PVs use `Retain`,
and the Terragrunt-owned Argo Application remains registered without a deletion
finalizer. Verify the gateway and any pending backup Jobs/Pods have fully stopped
before running the archive stage. Keep the old image, configuration and secrets
for compatible recovery.
Kustomize hashes the retirement scripts ConfigMap name so script changes replace
the reader Pod; its prior projected ConfigMap did not refresh in place.

After the bucket and one reader Pod are verified, run the protected fixed-stage
workflow from the exact current `main` SHA. Replace the placeholders with the
SHA and run IDs shown by GitHub Actions; never put private receipts in Git:

```sh
gh workflow run openclaw-enterprise-operations.yml --ref main \
  -f expected_sha=<CURRENT_MAIN_SHA> -f legacy_stage=inventory
# Verify a completed inventory's versioned off-NAS baseline. The original
# 39127113354 scan is the only allowed missing-object publication recovery.
gh workflow run openclaw-enterprise-operations.yml --ref main \
  -f expected_sha=<CURRENT_MAIN_SHA> -f legacy_stage=publish-inventory \
  -f baseline_ref=<INVENTORY_SHA>/<INVENTORY_RUN_ID>
gh workflow run openclaw-enterprise-operations.yml --ref main \
  -f expected_sha=<CURRENT_MAIN_SHA> -f legacy_stage=archive \
  -f baseline_ref=<INVENTORY_SHA>/<INVENTORY_RUN_ID>
# Wait for the private archive-result file after the detached worker finishes.
gh workflow run openclaw-enterprise-operations.yml --ref main \
  -f expected_sha=<CURRENT_MAIN_SHA> -f legacy_stage=publish-archive \
  -f baseline_ref=<INVENTORY_SHA>/<INVENTORY_RUN_ID> \
  -f archive_ref=<ARCHIVE_SHA>/<ARCHIVE_RUN_ID>
gh workflow run openclaw-enterprise-operations.yml --ref main \
  -f expected_sha=<CURRENT_MAIN_SHA> -f legacy_stage=verify \
  -f archive_ref=<PUBLISH_SHA>/<PUBLISH_RUN_ID>
# After final.json exists, prepare a separate private copy for compatibility review.
gh workflow run openclaw-enterprise-operations.yml --ref main \
  -f expected_sha=<CURRENT_MAIN_SHA> -f legacy_stage=prepare-restore \
  -f archive_ref=<PUBLISH_SHA>/<PUBLISH_RUN_ID>
```

Inventory binds the two SQLite databases, NAS root, historical checkpoint,
four PVC/PV UIDs, node and assistant image. Both inventory and archive refresh
Kubernetes status after scanning retained data and compare volume identities.
The stopped reader verifies SQLite from a temporary owner-only copy of each
database and its WAL under `/private/legacy`, because SQLite cannot rebuild
shared memory on the read-only source mount. It removes each copy after the
integrity check; the archive still includes the unchanged source files.
Inventory and the archive's stopped-source rescan run as detached read-only
processes from the reader's checksum-checked ConfigMap because a full NAS hash
can outlast one Kubernetes exec stream. The workflow polls the worker's
private completion marker; a failed scan uploads its private diagnostic to the
versioned backup bucket under
`openclaw-enterprise/legacy/<SHA>/<RUN_ID>/diagnostic.log`. A missing marker or
unfinished lock means the result is unknown; inspect the Pod and private log
before attempting another scan.
The `publish-inventory` verification accepts a completed inventory reference.
Only the completed `d55e2ab/39127113354` scan may publish a missing object;
other references must already have a published baseline. It requires the
success marker, matching worker and retained baseline copies, current
reader/PVC/root identity, and one exact
versioned S3 object whose downloaded bytes match. It does not rescan or stop
the old gateway. If publication fails or the object has multiple versions, keep
shutdown blocked and inspect the private failure; do not overwrite a version.
Unreadable zero-byte NAS files retain their empty hash and original mode in the
archive; unreadable files with data still stop the operation.
The archive stage refuses active or uncertain writers and starts a file-locked
worker in the reader Pod. The worker copies both source roots, checks the
stopped-source inventory again, and writes a private result only after a full
local restore. The writer keeps hardlink lookups in private local scratch
SQLite. Verification streams archive headers into a separate index on the same
local scratch; restored data stays on the archive claim. Both passes clear
Python 3.11's tar member cache. SQLite failures report only the fixed phase
and SQLite error code, without paths or database contents. An OOM-killed reader or
absent result leaves only a partial local archive; retain it for diagnosis
and start a new protected run only after the
cause is fixed. Do not treat a successful start as an archive receipt. Inspect
the private result and worker log before dispatching `publish-archive` with the
archive stage's SHA/run ID; the old source stays stopped and read-only while it
runs. Publication uses its own current-main SHA/run ID as a fresh immutable S3
prefix, so a failed attempt cannot overwrite an earlier completed or partial
object. The source archive SHA/run ID stays recorded in `final.json`. Publication
checks the completed receipt against the observed inventory, reads the bundle
in at most 8 MiB Kubernetes exec slices, and assembles 64 MiB S3 multipart
parts. It retries a broken or short slice up to three times and completes S3 only
after the full SHA256 matches the source receipt. A failed publication attempts
to abort its current multipart upload; bucket lifecycle cleans any abandoned ones.
Publication then downloads the versioned object to scratch and verifies a full
isolated extract in a detached worker before writing the private `final.json`
receipt. It rechecks zero writers and original volume identities immediately
before publication. Pass the successful **publication** SHA/run ID to `verify`;
it checks that identity in `final.json` before restoring the recorded versions.
Verify selects its original S3
version even after later versions or delete markers, then restores the archive
and receipt versions it recorded. A green inventory alone does not authorize
shutdown; the old Deployment and backup CronJob must first reach their reviewed
stopped GitOps state. If any stage
fails, leave old PVs, NAS data and credentials retained, inspect the private
diagnostic in the backup bucket if published, and retry with a new run ID after fixing
the cause. Never overwrite a completed S3 object version. An incomplete
multipart upload has no object version; after fixing its cause, the same
completed `archive_ref` can be retried through the protected workflow. The
bucket lifecycle aborts abandoned multipart uploads.

Large offsite publication needs a seven-hour AWS role session for the bounded
six-hour protected job. Before retrying `publish-archive`, apply and verify the
operator-owned role maximum through the
[duration-only saved-plan gate](../../../../docs/operator-infrastructure.md#legacy-archive-session-duration-rollout);
the workflow requests the same 25,200 seconds. Other AWS workflows retain their
existing session duration.

The tar keeps each source symlink's raw target without following it. Restore
verification validates all archive members and parent paths before extracting
non-link data without applying tar metadata, then restores safe file and
directory modes. It recreates links in private scratch only after checking
there are no archive members below a non-directory member and extracting all
non-link data. It compares every restored path, type, file hash and raw link
target with the stopped-source
content digest without following links.
Source UID, mode and mtime remain bound by the stopped inventory and rescan;
NAS all-squash changes them in private restore. Verification never follows
links. Some retained NAS links point to reader-Pod overlay directories outside
both archived roots; others are dangling. External target data is not in this
archive. T014 compatible recovery must classify those targets and prove any
needed data is separately retained or rebuilt before acceptance. Do not
blindly extract this tar into a live filesystem.

`prepare-restore` downloads the exact versioned archive, checks free scratch
space, and retains a verified copy at `/archive/private/rehearsal-<RUN_ID>/tree`.
Each versioned transfer fetches the pinned S3 version in at most 128 MiB ranges
and sends it to the reader in at most 8 MiB slices. The range response must
match the requested version, byte interval and length; each reader slice must
match its runner SHA-256 before append. Failed appends roll back to the last
committed offset. The reader promotes the aggregate only after its full size
and SHA-256 match; an incomplete transfer never becomes a restore input.
The archive digest comes from the published final receipt. The receipt digest
comes from a separate local download of the exact S3 version named in that
final receipt, so same-size transport corruption also fails closed.
The protected workflow reports fixed archive-download, receipt-download, and
restore failure phases without exposing private transport output.
Its private `link-classification.json` records raw targets as `contained`,
`link-chain`, `missing-in-archive`, or `external`. Its `lexicalPath` is a hint,
not proof that symlink components resolve there. `completed.json` records
only extraction and database integrity; its absence means the retained copy is
incomplete. Neither file belongs in Git or public CI logs. Absolute
links can still point at the original reader mounts: inspect every dependency
without following it, then mount isolated copies at the legacy paths before an
old-image boot. The NAS scratch copy has all-squash ownership, so local SQLite
state needs a separate UID 1000 filesystem and the parent/child bind-mount
identity from `values.yaml`. Keep all original claims read-only and the old
gateway at zero replicas. This preparation alone does not accept T014; prove
the isolated gateway can start without ingress or deliveries and recheck the
stopped production state and retained credentials first.

For compatible legacy recovery after a later Enterprise failure, first stop
the new agent through its supported API and prove its runtime is terminated.
Run the `verify` stage above, then restore the old Deployment replica count and
backup schedule through a reviewed GitOps change using the retained old image,
assistant checksum, PVs and secrets. Verify gateway readiness, a real turn and
the scheduled-job state before declaring recovery. Never import the legacy
archive into Enterprise.

### T014 isolated legacy boot gate

A read-only stopped-source review found 37 NAS symlinks. Nine absolute targets
leave both archived roots. Six point into `/app`: `plugin-skills` links for
`browser-automation`, `obsidian-vault-maintainer`, `wiki-maintainer`, and
`canvas`, plus the Discord extension and npm package links to `/app`. On
2026-10-20, the reader reported the pinned old image digest,
`readOnlyRootFilesystem: true`, a read-only root overlay, no `/app` volume, and
all five target directories present and nonempty. This proves that the pinned
image supplies a baseline for those six links. The former gateway did not set
`readOnlyRootFilesystem`, so its `/app` overlay could have held added or changed
files that the reader cannot see. The original contents of all six targets
remain unclassified until compared with retained evidence. The other three
external targets are dangling in the reader; their individual dependencies
and disposition also remain unclassified. The archive preserves each link,
but no external target payload. Do not assume the baseline image recovers the
gateway's exact contents or that the dangling links are harmless.

Archive verification and the retained original PVCs do not pass T014. The
reader restores into NAS scratch and does not start the old image. A rehearsal
needs a separate writable UID 1000 copy of the local parent/state/agent mount
layout, an isolated NAS copy, and a declared network boundary that prevents
Discord, heartbeat and job deliveries. Keep the original claims read-only and
the production Deployment and CronJob stopped. Flannel currently does not
enforce the declared NetworkPolicies, and no isolated canary is admitted; a
deny policy on a new Pod is therefore insufficient. Add and validate an
isolated old-image boot path before claiming compatible recovery, and require
the verified offsite archive receipt before running it. A reviewed offline
Linux container run with `--network none` could supply the network boundary,
but it still needs a proven container host, space for separate restored copies,
the pinned image digest, and UID 1000 writable mounts; no such rehearsal has run.
Without evidence of the former writable overlay, do not claim exact compatible
recovery from the image baseline alone.

OpenClaw targets Octelium app access as `openclaw.homelab`, while the stable UI
URL remains `https://openclaw.stinkyboi.com` and resolves to the Octelium
service address. Configuration and workspace remain on the `openclaw` NAS PVC.
Authoritative SQLite state and native threads use `openclaw-runtime-local`.

## Claw's assistant configuration

`assistant/` owns Claw's homelab personality, operating agreement, tool notes,
heartbeat checklist, model configuration, and scheduled work. Interactive
turns, heartbeat, and managed jobs use `openrouter/free` through the
[LiteLLM gateway](../litellm/README.md),
with medium reasoning and no silent fallback. `free` is the selection alias. The router
chooses a currently available free model that supports each request. Account
access must be verified with an actual turn; configuration validation alone
does not prove OpenRouter authentication or free-model availability. See the
[OpenRouter free-model router](https://openrouter.ai/collections/free-models/)
and the pinned [OpenClaw model reference](https://github.com/openclaw/openclaw/blob/v2026.9.5/docs/concepts/models.md).

Interactive turns have a one-hour execution budget (`agents.defaults.timeoutSeconds:
3600`). OpenClaw uses an absolute deadline: ongoing tool work does not reset
it. The former 600-second setting interrupted an active Discord
turn on September 21, 2026. Heartbeats retain 600 seconds; the morning brief,
health watch, and daily improvement retain 240, 180, and 600 seconds respectively.
If the deadline is reached, inspect completed work before retrying; the timeout
does not undo earlier actions. Roll back the default and bundle digest together
through GitOps.

OpenClaw authenticates to LiteLLM with the dedicated
`/homelab/openclaw/litellm-app-token`, exposed through a private file SecretRef.
LiteLLM owns upstream OpenRouter authentication. The
[assistant bootstrap](assistant/bootstrap.py) replaces provider/model maps,
limits every configured agent to the free router, disables OpenAI/Codex plugins,
and removes their active allowlist and auth-profile references. Private
credential files, original configuration, and recovery archives remain intact;
Astra/Codex is not an available inference or fallback route in current desired
state. Current [Helm values](values.yaml) install neither the Codex CLI nor its
code-mode host.

OpenClaw is pinned to `2026.9.5`. Bootstrap installs and verifies the external
Discord plugin at that exact version and takes a verified offline
`pre-2026.9.5` archive before applying runtime configuration. The retained
2026.9.2 checkpoint still protects the original local-storage cutover; preserve
both. A reviewed rollback to the historical 2026.9.2 configuration must restore
its matching image, plugin settings, and assistant checksum together through
GitOps. If state migration prevents the old runtime from starting, restore the
verified pre-2026.9.5 archive while stopped; an image revert alone does not undo
state migrations.

After sync, verify the Discord plugin version, readiness, a real Discord turn routed through
`openrouter/free`, and scheduled-job completion. Local validation cannot prove
account access.

### LiteLLM routing and Langfuse acceptance

The [managed provider configuration](assistant/config.json) sends
`openrouter/free` to `http://litellm.ai.svc.cluster.local:4000/v1` using the
dedicated gateway key. Preserve private historical OpenRouter/OAuth credentials;
they do not enable a direct-provider recovery route. Follow
[LiteLLM validation](../litellm/README.md#validation-and-rollout) for current
gateway authentication and inference acceptance.

Use Langfuse export at the gateway as the sole token-accounting source for
routed inference. The native OpenClaw plugin emits both per-call and run-total
usage, so enabling both would risk double counting. Gateway-only capture does
not cover native agent/tool lifecycle spans. Verify a real free-model turn and
its correlated Langfuse generation before claiming end-to-end tracing. Changes
to routing must document rollback of PVC-persisted settings. Native OTEL export
remains disabled in the managed configuration.

### Assistant behavior

The behavior is conversational and evidence-driven: remember corrections,
follow through on requested work, keep unchanged checks silent, and report
what was actually validated or deployed. Existing owner authorization for
homelab branch/PR/CI/merge work remains in force; branch policy and protected
deployment approval still apply. Proactive improvement is bounded to one open
PR and an eight-minute daily work window.

All schedules use `America/Los_Angeles` and deliver to the existing allowlisted
owner's Discord DM:

| Job | Schedule | Behavior |
| --- | --- | --- |
| Morning brief | Daily 09:00 | Calendar, tracked tasks, deals, health, next step |
| Health watch | :17/:47, 08:00-21:59 | New incidents or recovery |
| Daily improvement | Daily 14:30 | One verified improvement or PR |
| Heartbeat | Hourly, 08:00-22:00 | Follow up on tracked work |

The fixed-name ConfigMap mounts only in bootstrap and the app. Its content
digest in the Pod template triggers replacement when the bundle changes.
Bootstrap adds managed sections to SOUL.md, AGENTS.md, TOOLS.md, and
HEARTBEAT.md while preserving text outside those sections. It preserves IDENTITY.md, USER.md, MEMORY.md, daily notes,
existing tool additions, credentials, and unrelated config. It restricts managed
model policies to the free router instead of extending old provider allowlists. The first
pre-change files and config
are retained privately under `/data/openclaw/assistant-backups/v1`; this is a
same-volume rollback checkpoint, not an independent backup.

The app's postStart hook registers three jobs through the public automation
CLI with stable declaration keys. Retries converge in place; they preserve
job history and an owner's disabled state. It does not edit scheduler SQLite
tables or adopt, enable, disable, or delete unrelated jobs. An absent or ambiguous
owner defers
scheduling rather than guessing a recipient. This keeps a fresh gateway usable
before Discord setup. Bounded API retries also leave chat available on failure.
`/data/openclaw/assistant-reconciliation.json` records `deferred`, `pending`,
`failed`, or `ready` without credentials or recipient IDs. Verify `ready` in
addition to Pod readiness. After correcting a deferred/failed setup through
the declared configuration path, retry the reviewed reconciler:

```sh
kubectl -n ai exec deploy/openclaw -c app -- \
  python3 /etc/openclaw-assistant/reconcile.py
```

Existing alert hooks remain enabled.
See [OpenClaw automations](https://docs.openclaw.ai/automation/cron-jobs) and
[heartbeat behavior](https://docs.openclaw.ai/gateway/heartbeat).

### Historical subscription recovery (rollback only)

The retained helper below supports the former subscription configuration on
OpenClaw `2026.9.5`. It does not repair the current LiteLLM free-router path.
The chart does not mount this repository script; the commands below stream it
from the checkout to the container through stdin.
These steps apply only after a separately reviewed rollback restores the
matching provider/plugin configuration and an existing OpenAI OAuth profile.
Preserve the private credentials and backups; current bootstrap deliberately
removes their active configuration references.

If an operator-selected Astra recovery session reports `agent-runner-failure`
and gateway logs say its auth profile is temporarily unavailable, inspect
`openclaw models status --json`. A saved subscription block can outlive a provider usage reset:
auth preparation can reject a blocked profile before a background usage recheck. A valid OAuth expiry alone does not clear it.

Run the repository helper from this checkout:

```sh
node --check scripts/openclaw-recover-subscription.mjs
kubectl -n ai exec -i deploy/openclaw -c app -- \
  node --input-type=module - --check < scripts/openclaw-recover-subscription.mjs
kubectl -n ai exec -i deploy/openclaw -c app -- \
  node --input-type=module - --recover < scripts/openclaw-recover-subscription.mjs
```

Check mode is read-only and exits nonzero for the same blocked-profile
predicate used by auth preparation. Recovery invokes one upstream provider
usage recheck and waits up to 30 seconds for persisted recovery. OpenClaw owns
the transaction and verifies unchanged credentials and block generation;
provider denial, active authentication failures, and probe throttling retain
the block. It never spends a usage-reset credit, replaces credentials, edits
SQLite directly, or restarts the Pod. It accepts exactly one OpenAI OAuth
profile and the reviewed 2026.9.5 runtime; re-review its internal imports before
an upgrade. If it fails, inspect provider availability and auth diagnostics;
do not erase the block or repeatedly force probes.

After persisted recovery, the helper calls public `openclaw secrets reload`
to refresh the running gateway's separate auth snapshot. This re-resolves
existing secret references without editing them. Its command has a two-minute
deadline and a one-minute gateway timeout. An already-clear rerun still reloads
the gateway, so interrupted recovery converges without another provider probe.

After recovery, repeat check mode. To verify immediately without owner delivery,
enqueue a quiet internal system event, then inspect the completed heartbeat:

```sh
kubectl -n ai exec deploy/openclaw -c app -- openclaw system event --mode now \
  --text 'Recovery verification: read HEARTBEAT.md with your normal file tool, then reply exactly NO_REPLY. Do not notify anyone or start other work.' --json
kubectl -n ai exec deploy/openclaw -c app -- openclaw system heartbeat last --json
```

Require a newer successful heartbeat timestamp and check gateway logs.
Auth recovery alone is not
proof of inference or tool execution. No configuration rollback is needed:
only upstream availability bookkeeping changes, and subsequent provider
failures reinstate normal backoff. Remove the helper when upstream recovery
covers the native Codex path.

The September 6 incident also required clearing a missing native thread's
active context through the public session-reset lifecycle; all 244 original
transcript events were verified unchanged. That completed one-shot helper is
not shipped: the public reset API lacks an expected session generation, so a
preflight check cannot prevent owner activity from racing the reset. Future
recovery needs a conditional mutation API or an explicitly quiesced session.
Do not reset a live conversation using only a previously observed session key.
Run OpenClaw CLI diagnostics serially; the incident included SQLite contention
during concurrent diagnostic traffic.

### Validation

Before rollout, run the static gate and render app-template 4.4.0 plus this
Kustomize directory. The focused `scripts/ci/openclaw-assistant-check.py`
exercises preservation, repeatability, ambiguous routing, symlink rejection,
stable declarations, and the Pod content digest. After editing `assistant/`,
recompute the SHA-256 over sorted file names followed by a NUL byte and their
contents, and update `homelab.rst.io/openclaw-assistant-sha256` in values.yaml.

After the PR is merged and Argo syncs, verify:

```sh
kubectl -n ai rollout status deployment/openclaw --timeout=15m
kubectl -n ai exec deploy/openclaw -c app -- openclaw config validate
kubectl -n ai exec deploy/openclaw -c app -- openclaw models status --json
kubectl -n ai exec deploy/openclaw -c app -- openclaw automations list --all --json
```

Confirm one instance of each managed declaration, the intended Discord route,
and successful execution/delivery in automation run history. Send an owner
Discord message and verify the actual session model is
`openrouter/free` and the reply is
natural. Existing sessions with explicit model overrides must be inspected and
changed through an owner-authorized session/model operation; do not rewrite
session databases. Check monitoring/GitHub access using bounded read-only
queries; report missing access instead of claiming the tools work.

To pause a managed job, use `openclaw automations disable <job-id>`; its paused
state survives reconciliation. To retire or rename jobs, include explicit
removal of their declaration IDs in a reviewed maintenance change. Removing
the ConfigMap alone does not remove persisted jobs. Roll back through a PR
that restores the previous model and managed content and disables/removes
the three declarations through the public CLI. Keep personal memory and
session history; use the private originals only for a reviewed offline
workspace/config restore when needed.

## Resource Profile

The app container requests `1` CPU and `2Gi` memory, with `1500m` CPU and `4Gi`
memory limits. Seven days of five-minute samples measured about `1` CPU and
`1.8Gi` memory at p95. Multiple pod series exceeded `4Gi`, maxima approached
`6Gi`, and three terminated as OOMKilled. On 2026-08-28, app memory climbed to
`5.36Gi` immediately before its 8 GiB worker stopped reporting. The `4Gi`
containment limit deliberately prefers an app OOM over starving Talos, kubelet,
and containerd; raise it only after the memory growth is fixed and 48 hours of
healthy measurements show node headroom. The CPU limit throttles rare bursts
before they can starve a four-core worker. It requests
`8Gi` and limits `10Gi` of ephemeral storage: the shared
Nix store measured about `2.7Gi`; the now-retired toolbox Codex runtime had a
separate `2Gi` cap. That 2026.9.5 rollout exceeded the previous `6Gi` aggregate limit
after initialization and was evicted; the larger request covers the observed
footprint while the limit retains node protection. The `operator-toolbox` init
container requests `1` CPU and `2Gi` memory and limits `1500m` CPU and `3Gi`
memory. The bootstrap init container requests `500m` CPU and `1Gi` memory and
limits `1200m` CPU and `2Gi` memory. The local TCP proxy stays small at `25m`
CPU and `64Mi` memory requested, with `50m` CPU and `128Mi` memory limits.

OpenClaw excludes the `acer` control-plane node and every Octelium dataplane
node from scheduling. The 2026-08-25 recovery found bit corruption in both
`acer`'s cached image and control-plane etcd records. The dataplane exclusion
keeps OpenClaw's measured memory peaks from evicting ingress proxies. Remove
either affinity only after the affected node role has dedicated capacity and
passes its documented validation.

## Workspace Runtime Setup

The OpenClaw PVC is backed by the QNAP NFS share, so files under `/data/openclaw`
can appear owned by `nobody:nogroup` inside the container even though the app
runs as the `node` user. Startup bootstrap avoids fighting that ownership
mapping with `chown`. Instead it creates the expected workspace scratch paths,
including `/data/openclaw/workspace/.openclaw/trash`, and points Git at a
shared global config file on the PVC with safe-directory entries for the
workspace and `/data/openclaw/src/*` checkouts.

This keeps agent file cleanup and Git operations from failing on NFS ownership
metadata while preserving the PVC as the source of durable agent state.

Startup bootstrap also configures Claw's commits to be SSH-signed. The signing
key is generated once at `/data/openclaw/signing/claw_ed25519`, Git uses
`/data/openclaw/gitconfig` as its global config, and `commit.gpgsign=true`
prevents unsigned commits from being created by default. If the image does not
ship `ssh-keygen`, bootstrap unpacks `openssh-client` into
`/data/openclaw/tools` and points Git at that persistent helper.

The `operator-toolbox` init container installs the homelab operator tools with
Nix, shares `/toolbox/profile` with the app and bootstrap containers, and also
copies the complete init-container `/nix/store` with its database into the
shared `/nix` mount. Keep the store and database matched. Copying only the
profile closure while copying the full database leaves missing derivation paths,
which breaks fresh-pod `nix develop` runs against the homelab flake.

## Gateway Auth

The generated `/homelab/openclaw/app-secret` SSM parameter is exposed to the
pod as `OPENCLAW_GATEWAY_TOKEN`. Startup bootstrap stores
`gateway.auth.token` as a SecretRef to that environment value and pins
`gateway.auth.mode` to `token`, so the gateway does not depend on a generated
file under the container user's home directory.

If gateway startup reports a missing
`/home/node/.openclaw/secrets/gateway-auth-token.txt`, sync this desired state
and roll the pod. The environment token wins during startup auth resolution and
makes stale file-backed gateway token refs inactive.

If the Control UI reports
`unauthorized: device token mismatch (rotate/reissue device token)`, the browser
has a stale device-pairing token for the otherwise healthy gateway. Start with
read-only checks:

```sh
kubectl -n ai exec deploy/openclaw -c app -- openclaw gateway health
kubectl -n ai exec deploy/openclaw -c app -- openclaw devices list --json
```

If the gateway is healthy, refresh the browser's site data for the stable
`https://openclaw.stinkyboi.com` host reached through Octelium. Reconnect
through the current shared gateway-auth flow. To reissue a server-side token for
a paired Control UI device, identify the `clientId: openclaw-control-ui` record
and rotate its operator token:

```sh
kubectl -n ai exec deploy/openclaw -c app -- \
  openclaw devices rotate --device <device-id> --role operator
```

Treat any generated device token or token-bearing dashboard URL as secret
runtime material. Do not commit it or paste it into docs.

## Gateway Health

The gateway binds only to pod loopback on port `18789`; the `proxy` container
publishes it on service port `8080`. Both containers participate in pod
readiness through native HTTP probes against `/` on port `8080`, which avoids
spawning probe processes inside the containers while requiring the proxy to
connect to the gateway and relay a successful HTTP response.

The app container also owns startup and liveness probes. Startup allows up to
15 minutes for the gateway to load persisted state, plugins, and channels.
After startup,
36 consecutive failed liveness checks restart only the app container after
about six minutes without an HTTP response through the proxy. Readiness removes
the pod from the Service after two failures. A TCP-only check is not sufficient
here because the proxy listener can accept a connection even when its upstream
gateway is unavailable.

Initialization precedes those app probes. Two measured successful starts took
about 23 minutes, exceeding the default ten-minute Deployment progress deadline;
the pinned chart has no supported value for changing that field. Bootstrap uses
OpenClaw 2026.9.5's validated batches within existing configuration phases to
reduce repeated CLI invocations and writes. Private temporary batch files are
cleaned on exit. The runtime-backup CronJob shares sync wave `0` with the
Deployment so its desired state is applied before Argo waits for the long
rollout. See the [startup measurements and rollout checks](../../../../openwiki/operations/openclaw-bootstrap-batching.md);
actual improvement requires measurement after rollout.

Use the event timestamps to distinguish expected startup failures from a live
stall, then verify the gateway itself:

```sh
kubectl -n ai get events \
  --field-selector involvedObject.kind=Pod \
  --sort-by=.lastTimestamp
kubectl -n ai exec deploy/openclaw -c app -- openclaw gateway health
```

## Discord Channel

The `openclaw-secrets` ExternalSecret reads the Discord bot token from
`/homelab/openclaw/discord-bot-token` and exposes it to the pod as
`DISCORD_BOT_TOKEN`.

On pod startup, the `bootstrap-config` init container keeps the Control UI
origin allow-list current. It installs the official external
`@openclaw/discord` package from npm at the exact running OpenClaw image version
in pod-local plugin storage before validating persisted config. Bootstrap pins
the install and does not fall back to a floating release. When
`DISCORD_BOT_TOKEN` is populated, it enables and runtime-checks the plugin, then
stores a SecretRef to the environment-backed token. A missing or incompatible
exact package fails startup.
The npm cache and extension directory are intentionally not on the NFS-backed
state PVC because OpenClaw rejects code plugins owned by the QNAP NFS `nobody`
mapping.

Discord channel configuration is skipped when the SSM value is still
`REPLACE_ME`, so the app can start before the real Discord bot token exists.
The exact package still installs because its storage is rebuilt with every new
pod. After replacing the SSM value, bump
`homelab.rst.io/openclaw-discord-bot-token-ssm-version` in `values.yaml` to the
resulting SSM parameter version so Argo CD rolls the pod and the startup
bootstrap re-runs.

## Grafana Login

The `openclaw-secrets` ExternalSecret also reads the dedicated Claw Grafana
login from AWS SSM:

| SSM parameter | Pod surface |
| --- | --- |
| `/homelab/openclaw/grafana/username` | `GRAFANA_USERNAME` |
| `/homelab/openclaw/grafana/password` | `GRAFANA_PASSWORD` |

For in-cluster monitoring, use `http://grafana.monitoring.svc.cluster.local`
with this dedicated login. Grafana's Istio policy permits the OpenClaw service
account; Grafana still authenticates and authorizes API requests. The public
Cloudflare endpoint may reject non-browser clients with error 1010. Use the
Grafana datasource proxies for Prometheus metrics and Alertmanager alerts
instead of direct monitoring-service access. Grafana-managed firings are in
Alertmanager and do not appear in Prometheus ALERTS. Do not print Basic-auth headers or credential values.

OpenClaw has no Kubernetes service-account token or default kubeconfig. Bare
`kubectl` can contact its local proxy on port 8080 and return misleading results;
use Grafana monitoring unless a separate authorized kubeconfig is configured.

After replacing those placeholders, bump
`homelab.rst.io/openclaw-grafana-login-ssm-version` in `values.yaml` to the
latest SSM parameter version so Argo CD rolls the pod and reloads the
environment variables.

Validate after sync:

```sh
kubectl -n ai exec deploy/openclaw -c app -- openclaw channels list
kubectl -n ai exec deploy/openclaw -c app -- openclaw channels status --probe
```

The Discord bot must be invited to the target server and channel with at least
the permissions OpenClaw reports as required for Discord, including viewing the
channel and sending messages.

## Agent Hook

OpenClaw exposes an authenticated agent hook for callers that send its native
`message` payload. The hook token is generated at
`/homelab/grafana/openclaw-alert-hook-token` and exposed to OpenClaw as
`GRAFANA_ALERT_HOOK_TOKEN` only in the bootstrap container.

Startup bootstrap enables OpenClaw hooks at `/hooks` when the token is
populated. Alertmanager does not call this endpoint: its standard webhook body
does not include OpenClaw's required `message` field. Homelab alerts are sent
through Alertmanager's native Discord receiver instead.

OpenClaw rejects SecretRef objects for `hooks.token`, so bootstrap expands
`GRAFANA_ALERT_HOOK_TOKEN` from the mounted Secret at pod startup, JSON-encodes
the actual runtime value, and writes that plain string to the PVC-backed
OpenClaw config. This keeps the token out of git while satisfying OpenClaw's
hook-token policy. Configuration writes happen during init before the gateway
runs; a failure prevents startup.

After rotating the hook token, bump
`homelab.rst.io/openclaw-grafana-alert-hook-ssm-version` on OpenClaw so Argo CD
refreshes the Secret and rolls the pod that reads it.

## GitHub App Credentials

OpenClaw receives GitHub App identity through AWS SSM-backed ExternalSecrets:

<!-- markdownlint-disable MD013 -->

| SSM parameter | Pod surface |
| --- | --- |
| `/homelab/openclaw/github-app/id` | `GITHUB_APP_ID` |
| `/homelab/openclaw/github-app/installation-id` | `GITHUB_APP_INSTALLATION_ID` |
| `/homelab/openclaw/github-app/private-key` | `/var/run/secrets/openclaw/github-app/private-key.pem` |

<!-- markdownlint-enable MD013 -->

The pod sets `GITHUB_APP_PRIVATE_KEY_PATH` to
`/var/run/secrets/openclaw/github-app/private-key.pem`. The private key is
mounted as a file from `openclaw-github-app-private-key`, so the PEM is not
copied into the process environment. Other OpenClaw secret keys are mapped with
explicit `secretKeyRef` entries rather than a broad `envFrom` import.

After replacing any GitHub App SSM placeholder, bump
`homelab.rst.io/openclaw-github-app-credentials-ssm-version` in `values.yaml`
to the resulting SSM parameter version so Argo CD rolls the pod and reloads the
environment variables.

The managed `assistant/gh` wrapper precedes the toolbox on the app's PATH.
It signs a GitHub App JWT using Node's built-in crypto, requests a fresh
installation token for `homelab`, and passes it through a private temporary
native CLI config file. Each invocation cleans up its own file; no token is
stored on the PVC or injected into a subprocess environment. The temporary
`GH_CONFIG_DIR` is an internal per-process path, not a desired-state input.
Tokens expire after one hour; renewal happens on every command, without a
timer or cached credentials. Git HTTPS uses this wrapper as its credential
helper. Existing commit signing remains separate.

The token requests contents, pull requests, issues, and workflows write access,
plus Actions, checks, statuses, and metadata read access. It does not request
the installation's administration or secret-management permissions. See
[GitHub's installation-token flow](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app).

Verify from the app container using `gh api repos/Stuhlmuller/homelab/pulls
--jq length` and `gh api installation/repositories --jq '.repositories[].full_name'`.
The second command must list only `Stuhlmuller/homelab`. A missing/invalid key,
denied token request, or missing installation access fails closed; do not print
tokens or use another account to bypass it. Run `node
scripts/ci/openclaw-github-check.cjs` locally for signing, scope, renewal, private
file permissions, cleanup, CLI exit-code propagation, and failure checks.
Rollback by reverting the wrapper, PATH, Git helper, and assistant bundle digest
through GitOps. Live acceptance remains pending until the new pod passes these
authenticated reads.

## OpenRouter Free Through LiteLLM

Do not store OpenRouter keys, ChatGPT passwords, browser cookies, or OpenAI API
keys in this repo. The [ExternalSecret](externalsecret.yaml) supplies the
dedicated LiteLLM caller key; bootstrap writes its private file for the managed
provider SecretRef. Upstream OpenRouter credentials are managed by
[LiteLLM](../litellm/README.md#ui-managed-openrouter-credential).

The pod startup bootstrap sets `openrouter/free` as the default and
keeps fallbacks empty. It removes subscription provider/model configuration and
disables the OpenAI/Codex plugins. Historical session records and private OAuth
files may remain; their presence does not establish an active recovery route.
Inspect effective session routing without rewriting history.

The pinned release uses four concurrent runs. Before applying configuration,
the stopped gateway's bootstrap verifies its release-specific offline archive
under `/data/openclaw-backups`. Archives include credentials, transcripts,
workspace, and authoritative local state; keep them private. They share the
NAS failure domain and do not replace an independent backup. Reinstallable npm
cache and plugin directories are excluded. Recover from a verified archive
with matching software while the gateway is stopped; an image-only rollback
does not restore persisted state.

The bootstrap also enables the bundled `memory-wiki` plugin. OpenClaw uses that
plugin for Imported Insights and Memory Palace, so reload the Control UI tab
after the synced pod restarts if those views still show an enable-plugin prompt.

Startup bootstrap pins `agents.defaults.sandbox.mode` to `off`. OpenClaw
[2026.8.2 supports Docker, SSH, and OpenShell sandbox backends](https://github.com/openclaw/openclaw/blob/v2026.8.2/docs/gateway/sandboxing.md).
This Talos pod has no Docker daemon, while the repository declares neither a
dedicated SSH target and trust material nor an OpenShell account/runtime.
Enabling `non-main` without a working backend makes Discord, group, and spawned
agent runs fail before reply.
The containment boundary is the Kubernetes workload: the service account token
is disabled and ambient mesh policy restricts ingress. The NetworkPolicy records
intent but flannel does not enforce it. Egress is not restricted, and all
sessions share the pod's persistent workspace, operator toolbox, and mounted
application credentials. If a sandbox backend is added later, document and
validate it before changing this setting.
Do not mount a host container-runtime socket into this workload.

Bootstrap installs the official external Discord plugin before validating
persisted config and applying desired state. A matching installed version is
reused; missing or mismatched packages get four bounded registry attempts.
Bootstrap pins `gateway.mode` to `local`; external-supervisor mode makes
Kubernetes the lifecycle and image-update authority.

Bootstrap enables the bundled OpenRouter provider plugin with the managed
LiteLLM base URL. After connecting through Octelium, verify the configured
default and model discovery through that gateway:

```sh
kubectl -n ai exec deploy/openclaw -c app -- \
  openclaw models status --json

kubectl -n ai exec deploy/openclaw -c app -- \
  openclaw models list --provider openrouter
```

Require an actual free-model turn to verify inference; model discovery alone
does not prove it. Restore lost persistent state from a verified archive and
let the declared secret/configuration path restore gateway authentication.
Historical OpenRouter/OAuth files remain private recovery material, not active
provider configuration.

## Durable runtime state and recovery

Heartbeat retains a 600-second budget; the interactive agent default is 3600
seconds. The scheduler's
heartbeat watchdog includes waiting for existing replies/background jobs and
its 60-second idle retry grace, not only model execution. A 120-second budget
produced a failed receipt after about 80 seconds of scheduling delay plus a
43-second successful agent turn. Keep this queue-inclusive budget when tuning
heartbeats; do not mistake a completed native turn for a successful cron receipt.

The platform-storage application declares the retained 5 GiB local PV in
`clusters/homelab/platform/storage/openclaw-runtime.yaml`; this application
declares only its namespaced claim in `runtime-storage.yaml`. The PV resides at
`/var/lib/openclaw-runtime` on `zimaboard-1`. This is Talos EPHEMERAL partition
storage, survives Pod replacement, and is lost if that node's disk is wiped.
The hostPath capacity is a scheduling declaration, not a filesystem quota.
Monitor node free space. The Deployment is pinned to that node with one replica
and `Recreate`; automatic failover to another node is intentionally unavailable.

Talos runs kubelet in a container. An arbitrary host path used with `subPath`
can resolve inside kubelet's overlay instead of the CRI host filesystem. The
application therefore uses direct child PVs for `runtime/state` and
`runtime/agents/main/agent`; the parent PV provides the integrity-check and backup view.
These three retained PVs describe the same underlying directory tree, not three
independent disks. Bootstrap requires identical database device/inode identities
through parent and child mounts before starting any OpenClaw CLI.

The retained `pre-2026.9.2-runtime` database checkpoint supplements the full
pre-upgrade archive. The first full archive was produced while the incorrect
subpath mounts hid the databases; restore this checkpoint together with that
archive. The checkpoint uses SQLite backup, hash, and integrity verification
before its completion marker, and is separate from daily snapshot retention.
See [Talos mount propagation](https://www.talos.dev/v1.12/talos-guides/configuration/disk-management/user/).

The Enterprise retirement reader runs as one read-only Pod after this GitOps
change and uses a retained `openclaw-retirement-archive` claim. It mounts the
parent and both child local PVs separately
from the NAS claim, so its archive contains the real NAS files and both local
SQLite databases without an overlaid mount hiding either copy. The reader has
no ServiceAccount token, no listener and a deny-all NetworkPolicy. Verify the
off-NAS bucket, reader readiness and retained PVC identity before running the
protected inventory. If readiness or mount identity fails, return the reader to
zero replicas through GitOps; keep the legacy writer active and do not archive
or shut it down. The archive claim is scratch on the same NAS, so an independently
verified off-NAS copy is still required before retirement is accepted.
Provision the versioned off-NAS bucket through the protected Terragrunt Apply
workflow on the current `main` SHA with `application_backup_storage=true` and
an empty Argo CD target. Verify an upload and independent download before
stopping the old writer; the reader's NAS scratch claim alone is insufficient.

The init-only `runtime-storage.py verify` requires both authoritative SQLite
databases and checks integrity and foreign keys without modifying them. Missing
or corrupt local state blocks startup and requires a verified snapshot restore.
The root toolbox init initializes only the volume root; verification runs as
UID 1000. Bootstrap then verifies parent and child mounts identify the same
files before running any OpenClaw command.

The mounts at `/data/openclaw/state` and `/data/openclaw/agents/main/agent` let OpenClaw
select WAL on a local filesystem. Its network-filesystem policy keeps NFS in
rollback-journal mode, where long readers can block write commits. The native
Codex home from the retired subscription runtime is retained under the same
local agent tree. Workspace, identity/configuration files, and existing archives remain
on the original NAS claim. The pre-upgrade archive explicitly includes the two
local mount roots despite `tar --one-file-system`. If a rollout interrupts archive creation, bootstrap preserves the unpublished partial directory with an `interrupted-<UTC timestamp>` suffix and rebuilds from the still-stopped state. A corrupt published backup still blocks startup; it is never replaced automatically.

`runtime-backup.yaml` takes daily online SQLite snapshots at 04:25 Pacific using
SQLite's backup API, verifies them, records hashes, and retains seven completed
snapshots on the NAS at `/data/openclaw-runtime-snapshots`. Source databases mount
read-only; committed WAL data is included. These are authoritative database
snapshots, not full-machine backups: workspace/configuration already live on the
NAS, and retained Codex indexes belong to historical recovery state. Snapshot
artifacts contain credentials and private history; keep their permissions private.

After sync, verify integrity-check logs, WAL mode for both authoritative databases,
repeated main-session turns and heartbeats, the real owner Discord round trip,
and one online backup through the same repository helper:

```sh
kubectl -n ai logs deploy/openclaw -c 01-runtime-storage
kubectl -n ai exec deploy/openclaw -c app -- \
  python3 /etc/openclaw-assistant/runtime-storage.py backup
kubectl -n ai exec deploy/openclaw -c app -- openclaw channels status --json
```

Rollback is a reviewed GitOps storage/restore change, never an image-only revert:
after local writes start, the old NAS databases are stale. Quiesce the Deployment
through repository code, verify the latest snapshot hashes and SQLite integrity,
restore into a new stopped target with compatible software, and repoint the
mounts through GitOps. Do not overwrite a live database or prune either retained
claim. If the local node is lost, the database recovery point is the latest
successful daily snapshot; fresh native threads reconstruct available canonical
context. The original pre-upgrade archive remains the downgrade recovery source.

## Local identity coordinator

OpenClaw 2026.8.2 requires its coordinator directory to belong to the runtime
UID and have mode `0700`. The QNAP share reports UID/GID `65534` for persistent
state, while the image runs as UID `1000`; the gateway otherwise refuses
startup with `device identity coordinator directory belongs to another user`.

Mount a shared 16 MiB `emptyDir` only at
`/data/openclaw/tmp/openclaw-1000` in bootstrap and the gateway. The existing
root toolbox init sets this local volume to `1000:1000`, mode `0700`, before
OpenClaw runs. Upstream ownership and locking checks remain enabled. Device
identity, configuration, session SQLite databases, and backups stay on the
retained PVC; the old NAS lock directory is hidden, not removed.

This relies on the existing single-replica `Recreate` controller. All writers
must run in this Pod and share its coordinator mount. Do not run a second
Pod or external doctor process against the same PVC: separate local lock
volumes would not coordinate those writers. Stop the gateway through a
reviewed declarative maintenance change before any external state repair.
Revisit this storage design before introducing multiple replicas.

Validate the render and the full static gate before rollout. After Argo sync,
require the mounted directory to report UID/GID `1000:1000` and mode `0700`,
then verify gateway readiness and the Discord channel.
Rollback removes the local mount through a reviewed PR; persistent data and
backup files remain, but the known NAS ownership failure would return unless
an alternative ownership-compatible storage path is deployed first.

## Container privilege boundary

The gateway, bootstrap, and proxy run as UID/GID 1000, drop all Linux
capabilities, and deny privilege escalation. The Pod explicitly selects the
runtime's default seccomp profile. The proxy listens on unprivileged port 8080
and needs no root identity or network capabilities.

The Nix toolbox init remains a root exception: it copies the shared Nix store
and assigns UID 1000 ownership before the non-root containers start. This Pod
therefore does not claim full Restricted Pod Security compliance. Keep the
exception scoped to that init container; moving installation into a built
image would permit a separate reduction later.

Validate the rendered contexts and server-side dry run before rollout. After
Argo CD reconciles, require successful toolbox/bootstrap completion, gateway
readiness, a read-only Discord credential probe, and operator-tool execution.
The effective app/proxy process must report `NoNewPrivs: 1`, zero `CapEff`,
and seccomp filtering in `/proc/self/status`. Revert these Helm values through
GitOps if a required runtime operation fails; do not patch the live Pod.

## Personal assistant integration status

The managed agreement covers Google Calendar, computer-deal research and
bounded Marketplace seller outreach, plus private task/deal ledgers. Discord
remains owner-scoped. Existing homelab fixes retain the PR/CI/GitOps workflow.
The morning brief includes calendar/tasks/deals when connected; it does not send
seller messages or create an unrequested shopping schedule.

The toolbox adds gogcli 0.11.0 from the existing pinned nixpkgs revision and
bootstrap enables the bundled gog skill, preserving unrelated skill settings.
Google Calendar is the owner's selected provider. This installs capability;
it does not authorize an account. Follow the version's `gog auth --help` and
[upstream authentication documentation](https://github.com/steipete/gogcli/tree/v0.11.0)
for Calendar-only OAuth. Personal account identity, client material, refresh
tokens, and any keyring unlock secret must stay outside git and Discord.
A persistent, file-backed credential contract and owner OAuth consent are still
required before unattended calendar use. Do not add environment-based desired
state or enable unrelated Google services to work around missing credentials.

Live inspection on September 7 found Discord enabled and the Pod 2/2 Ready,
but no gog executable, Chromium executable, or configured browser profiles.
Marketplace therefore also needs a repository-owned private browser backend
and owner login using OpenClaw's [browser integration](https://docs.openclaw.ai/tools/browser).
No browser service, public debugging port, Facebook session, or OAuth credential
is created by this change. The owner still needs to specify hardware targets,
total budget, pickup area/radius, and shipping preference before outreach.

Acceptance after GitOps rollout: verify `gog --version`, the enabled skill,
managed workspace sections, and owner Discord request/reply. Google acceptance
requires a successful bounded event read and an owner-requested event write/readback.
Marketplace acceptance requires authenticated listing access and a scoped,
owner-requested seller message verified in its conversation. Keep each blocked
capability explicit; do not label either integration operational before these pass.
Rollback through git by reverting the bundle/toolbox changes and digest; preserve
private task notes and any account credentials, and revoke account grants only
when explicitly requested.
