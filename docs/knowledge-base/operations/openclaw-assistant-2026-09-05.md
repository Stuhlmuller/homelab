# OpenClaw assistant rollout, September 5

## Desired state

[PR 963](https://github.com/Stuhlmuller/homelab/pull/963) configures Astra via
the existing Codex harness, managed workspace instructions, an owner Discord
briefing, daytime health checks, and bounded daily improvements. Argo observed
merged revision `2c089558100fd09de969cda78bf3633cde6fe0b1` and created its
replacement Pod. PR 964 subsequently bounded doctor runtime and replaced that
Pod during bootstrap; verification follows the replacement. Both migration
markers survived. Runtime acceptance remains open until verified below.

The live scheduler inventory contained five enabled jobs. Reconciliation
replaces Grafana auto-triage and the older daily improvement loop while
preserving their history and unrelated security, memory, and research jobs.
Exact retired identities are in the app's `assistant/retired-jobs.json`.

## Startup performance finding

- **Evidence:** The prerequisite workspace-migration Pod spent about nine
  minutes building/copying the operator toolbox and about twenty minutes in
  bootstrap. Between 14:25 and 14:29 UTC, consecutive configuration commands
  took roughly twenty seconds each and emitted `slow SQLite transaction hold`.
  Doctor completed the remaining state migration and verified preserved session
  identities at 14:39 UTC.
- **Evidence:** The gateway reported ready at 14:41 UTC, but the Pod remained
  unready and emitted `slow SQLite transaction lock wait` and delayed liveness
  diagnostics before the assistant rollout replaced it. A gateway-ready log
  alone is not proof of HTTP readiness or responsive Discord operation.
- **Impact:** Repeated Pod replacement incurs substantial downtime. The
  retained state is QNAP-backed; the exact cause of transaction contention is
  not yet established. Do not attribute it solely to NAS latency from these
  logs.
- **Next steps:** Measure the proxy `/` response, CPU throttling, active
  automation workload, and shared SQLite transaction contention after startup.
  Profile or batch configuration writes through reviewed bootstrap code. Keep
  verified backups and session-preservation gates; do not interrupt migration
  or patch live state to obtain a green readiness signal.

## Acceptance evidence

Confirmed before rollout: pinned OpenClaw config validation, installer and
scheduler regression tests, full static checks, exact Helm/Kustomize renders,
300 rendered Kubernetes policy assertions, lint, secret scanning, and required
GitHub checks passed.

A read-only inspection of all 19 current session metadata rows found no
explicit model or provider overrides, so no session-route migration is needed.

The replacement Pod completed bootstrap at 15:18 UTC without a restart. Its
persistent default is `openai/gpt-6-astra` with an empty fallback list; managed
workspace installation and pinned-runtime config validation passed. Discord's
plugin was enabled. Gateway readiness and model execution remain separate checks.

At 15:21 UTC the gateway returned HTTP 200 and reconciliation recorded `ready`.
The Pod reached 2/2 Running with zero restarts. Public automation inventory
confirmed all three Astra declarations with Pacific schedules and Discord
delivery, and both overlapping legacy jobs disabled.

An actual gateway-backed Astra turn failed with `Unknown model` from the Codex
runtime. Configured model presence is insufficient: its catalog entry reports
`available: false`. The bundled Codex is `0.151.0`; OpenAI added Astra support
in `0.153.1`. The follow-up pins `0.153.2` with verified release digests and
selects that binary through the plugin's supported app-server command setting.
Source inspection confirms OpenClaw `2026.9.1` requests hidden models;
`2026.8.2` does not. The follow-up therefore upgrades the gateway and installs
the exact matching official Codex plugin, retaining the native binary override.
A verified offline `pre-2026.9.1` archive precedes the new runtime commands.
Actual post-upgrade inference still needs testing.

The upgraded Pod reached 2/2 Running with no restarts, verified Codex 0.153.2,
and reconciled the scheduler. The next real Astra turn passed model discovery
but failed with `No route-compatible authentication source is configured`.
The OAuth profile remained configured; source inspection showed Astra absent
from the default dual-route list. The follow-up explicitly selects the official
ChatGPT subscription adapter. Executing the pinned runtime's route resolver
with this configuration confirms one subscription route compatible with Codex.
Live inference remains the acceptance gate.

Still required: successful Astra inference, confirmed Discord delivery, and a
successful bounded health check using real homelab tools after the runtime fix.

## Stale subscription block, September 6

At 18:39 UTC, `heartbeat-main` failed with `agent-runner-failure`; gateway
auth preparation rejected Astra before inference. The saved auth usage state
held an account-wide `subscription_limit` block from `wham`, expiring at
02:29 UTC September 7. A read-only provider usage request with the same
OpenClaw credential returned `allowed: true`, `limit_reached: false`, and
6 percent weekly use. The credential had not expired. This is a stale local
block, not evidence that another login or paid usage reset is needed.

`scripts/openclaw-recover-subscription.mjs` uses the pinned runtime's actual
cooldown predicate for its read-only check, and its native generation-checked
provider recheck for recovery. The original check reproduced the failure.
The helper fails closed on other versions, ambiguous profiles, unrelated auth
failures, or provider denial. See the app README for execution and rollback.
Native provider recheck cleared the saved block; a separate public
`secrets.reload` was necessary to refresh the running gateway auth snapshot.
The next heartbeat reached Codex but failed with `thread not loaded` for its
retained main-session binding. The per-agent Codex home is rebuilt on Pod
replacement; that retained binding did not recover transparently in this run.
A one-shot public session-reset recovery ran for this failed session.
At 19:03 UTC it cleared
active model context and the native binding while verifying all 244 original
canonical transcript events remained unchanged. Workspace memory is preserved.
At 19:08:43 UTC the next isolated verification completed on
`openai/gpt-6-astra`, with run status `completed` and outcome `mute`.
Canonical transcript records show successful `bash` and `heartbeat_respond`
tool results. The preceding attempt had reached tools but failed saving plugin
state with `database is locked`; the successful retry ran without concurrent
OpenClaw diagnostic CLI commands. This establishes recovery, not resolution
of the underlying intermittent SQLite contention.

The recovery regression suites and the assistant preservation/scheduler suite
passed locally. The initial PR revision also passed GitHub static policy and
security checks plus the Terragrunt gate; later revision checks must be checked
on the PR. Local full Nix validation was unavailable because the sandbox denied
its cache lock, and the existing config checker lacked local `yq`.

Review identified a race between the one-shot reset preflight and the public
mutation: the API accepts no expected session identity/generation. The already
completed reset helper and its tests were removed before merge. Any future
reset recovery must use atomic conditional identity checks or explicit session
quiescence; prior successful execution does not make the helper safe to reuse.

Follow-up: verify retained native bindings recover across Pod replacement
before treating the Codex home as universally rebuildable. Do not make it
persistent on NFS without reviewing SQLite/storage implications. Existing
SQLite lock contention also delayed maintenance and CLI diagnostics during
this incident; its underlying cause remains unverified.

## Sources

- `clusters/homelab/apps/openclaw/README.md`
- `clusters/homelab/apps/openclaw/assistant/`
- [[workloads/application-notes#OpenClaw]]
- [[architecture/storage-and-state]]

## Authenticated model preparation follow-up

PR 971 selected subscription authentication, but the real gateway turn then
failed with `Unable to materialize openai/gpt-6-astra for its prepared
subscription route`. The pinned fallback builder only synthesizes unknown
models before an auth profile is selected. An explicit Astra subscription
model row supplies the missing metadata, retaining native account checks.
A temporary `agent exec` test did not inherit a usable credential; it is not
proof of gateway inference. Validate the actual gateway after rollout.

## Native tool execution follow-up

After PR 974, the gateway returned an actual `ASTRA_READY` response. Its terminal
receipt confirmed requested, effective, and response model `gpt-6-astra`, native
Codex harness, and no rerouting or fallback. A second Astra turn was delivered
successfully to the owner through Discord (`deliveryStatus.status: sent`).

That second turn exposed a separate tool failure: `failed to spawn code-mode
host /toolbox/codex/codex-code-mode-host: No such file or directory`. The toolbox
had installed only the main Codex binary. The follow-up installs the matching
0.153.2 code-mode host beside it, verifying the official architecture-specific
release digest. Live read-only tool acceptance remains required after rollout.

The public scheduler inventory also showed the daytime health job auto-disabled
after ten pre-fix authentication errors. Recovery matches only that recorded
auto-disable timestamp, declaration, and auth reason, then uses the public enable
command. Operator pauses and any later automatic pause remain untouched. Revert
the recovery code to prevent this specific restoration; ordinary operator
pausing remains supported. No scheduler database mutation is used.

## Monitoring access acceptance

PR 979 deployed successfully. The new code-mode host completed a local protocol
execution test, and an actual Astra turn then read `TOOLS.md` and executed a
command with no model fallback. All three managed schedules were enabled; the
health watch had a successful scheduler run. This proves tool execution, not
that monitoring data was available.

The next acceptance check found no default Kubernetes context. Bare kubectl
reached OpenClaw's local port 8080, whose `/readyz` response is not Kubernetes
health. The public Grafana endpoint returned Cloudflare error 1010; the internal
service reset the connection because OpenClaw was absent from its Istio client
allowlist. Add only `cluster.local/ns/ai/sa/openclaw` to the existing Grafana
policy and use the dedicated Grafana login with the internal service URL.
Grafana application authentication remains enforced; direct Prometheus access
and Kubernetes API privileges remain unchanged. Roll back by removing that
principal through GitOps. Verify authenticated datasource discovery and actual
Prometheus query results from an Astra tool call after sync.

The managed `TOOLS.md` carries this monitoring path and the bare-kubectl guard.
Its content digest triggers a rollout so scheduled checks receive the corrected
instructions. The canonical mesh table and workload inventory record the new
OpenClaw-to-Grafana dependency.

Health checks must inspect both Prometheus metrics/rules and Alertmanager via
Grafana datasource proxies. Most homelab rules are Grafana-managed and publish
to Alertmanager, so an empty Prometheus ALERTS result cannot establish that no
alerts are firing. Managed instructions now require both sources and explicitly
report partial visibility if either fails.


## Durable reply and heartbeat repair, September 6 Pacific

The owner Discord round trip was confirmed directly through Discord at 01:20 UTC
September 7: an owner-originated `reply test 323` received the bot response
`test 323` approximately 18 seconds later. Outbound-only testing had been
insufficient to establish this. Earlier hourly heartbeat receipts still showed
repeated `thread not loaded` failures; a separate quiet test reproduced a SQLite
plugin-state write failure, and a serial retry succeeded.

The deployed 2026.9.1 Codex adapter performs `prepareCodexThreadResume` outside
`resumeExistingCodexThread`'s recovery boundary. Stable 2026.9.2 supplies it as
`prepareResume` inside that boundary and adds session ownership fencing. Upgrade
the gateway and both external plugins together. Keep Astra and the verified
native code-mode host; do not reset sessions or bypass owner checks.

The SQLite runtime explicitly selects rollback journaling on NFS and WAL on
local filesystems. Move only `state/` and `agents/main/agent/` to a retained local PV on
`zimaboard-1`, preserving the NAS source and verifying the offline copy before
startup. Native Codex state now survives Pod replacement. The old NAS native
cache is excluded because it was hidden by the previous emptyDir. Workspace, archived transcripts, and
configuration remain on NFS; daily online SQLite backups preserve committed WAL
and keep seven NAS recovery points. See the app README for cutover, verification,
and rollback. Node-disk loss requires snapshot restore and can lose writes since
the last successful snapshot.

Migration/backup regression tests cover history preservation including embedded
NULs, live committed WAL, corruption rejection, retries without stale recopy,
and preservation of an unmarked existing target. Helm/Kustomize rendering and
Kubernetes server-side dry runs passed. `nix run .#validate` is absent in this
checkout; `nix develop -c bash scripts/ci/static-checks.sh` passed instead.
Deployment and repeated runtime acceptance remain required before marking this
repair complete.


Argo CD rejected PR 993's initial storage placement before changing the live Pod:
`homelab-workloads` intentionally disallows cluster-scoped resources. The follow-up
moves the StorageClass/PV into the existing platform-storage application and keeps
only the PVC in OpenClaw. Project permissions remain unchanged. Kubernetes API
dry runs do not validate Argo AppProject permissions; static validation now also
checks that OpenClaw's rendered manifests contain no StorageClass or PV.

The migration also fails closed if local state is missing after the retained
pre-2026.9.2 backup marker exists. Bootstrap writes that marker before the new
Gateway starts. This prevents a replaced/lost node disk from silently importing
stale NAS databases; recovery requires an explicitly reviewed snapshot restore.
The regression test covers both missing-local refusal and valid-local restart.
