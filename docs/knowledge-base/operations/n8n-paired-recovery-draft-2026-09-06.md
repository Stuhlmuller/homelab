# n8n Paired Recovery Draft

Status: design only. No maintenance window, recurring interruption, rollout,
new storage provider, or backup controller is approved by this note.

Use a **fenced n8n maintenance checkpoint**, followed by an isolated restore.
Do not count an online PostgreSQL dump plus an independently copied `.n8n`
directory as a coherent recovery set. Keep issue
[#792](https://github.com/Stuhlmuller/homelab/issues/792) open for independent
backup and workload recovery coverage.

## Runtime And Consistency Contract

The repository and Argo declare one `Recreate` n8n Deployment, PostgreSQL 14.23,
and separate retained NFS claims for the database and `/home/node/.n8n`.
`clusters/homelab/apps/n8n/values.yaml` pins image digest `307d6065…53b1ec`.
September 6 read-only inspection found that same live digest, Argo
`Synced/Healthy`, and CLI version **2.37.10**. Older upgrade draft #855 assumes
a different starting version; do not use its proposed 2.36.8 image for recovery
without reconciling that discrepancy. Record and verify the exact application
and PostgreSQL image identities in every recovery set.

The following findings use upstream tag `n8n@2.37.10`, commit
`5542b8b6419cb6925cca8f11b270c9bfbe09d85e`:

- Regular execution mode defaults to **filesystem binary storage**. Files may
  reside under `.n8n/storage` or the retained legacy `.n8n/binaryData` path;
  execution-data storage can also use the filesystem. Preserve the entire
  declared data tree and fail preflight if any effective storage path escapes
  the backed-up mounts. Do not assume filesystem data is unused because a
  setting is absent. [Binary configuration][binary-config], [storage paths][storage-config].
- The blob manager writes file bytes and companion metadata separately, and
  supports subsequent deletion. PostgreSQL's dump snapshot cannot freeze those
  filesystem operations. **Inference:** without an application-wide barrier or
  a demonstrated cross-store snapshot protocol, live copies can lose a binary
  referenced by the database or capture incomplete metadata. Extra files do not
  prove that every referenced file exists. [Blob implementation][blob-manager],
  [PostgreSQL dump consistency][pg-dump].
- The persisted `.n8n/config` contains the instance encryption key; an
  incompatible supplied key is rejected. The repository uses the SSM bootstrap
  key only when that file is absent. The optional rotation feature stores
  wrapped data keys in PostgreSQL, retains older keys, and resolves ciphertext
  by key ID using the instance key. Preserve the matching config and **all**
  database key rows, not just the active key. No root-key replacement, data-key
  rotation, storage-mode migration, or application upgrade may overlap capture.
  Record feature flags without recording key material in public metadata.
  [Instance settings][instance-settings], [key manager][key-manager], [cipher][cipher].

There is no demonstrated online joint-backup protocol in the repository. The
current NFS provisioner also supplies no declared cross-volume snapshot group.
A future online design must prove the barrier across DB commits, file writes,
pruning, and key changes; timestamps, two successful copy commands, or a quiet
traffic sample are insufficient.

## Ownership And Maintenance Sequence

Keep Argo responsible for n8n replicas and routes. `IaC/terragrunt.stack.hcl`
enables automated self-healing for n8n and n8n-postgres. A CronJob that scales
the Deployment would conflict with that ownership. Do not introduce replica
ignore rules, disable self-healing, grant a backup Pod scale/patch/delete rights,
or use sync waves alone as evidence of a stopped writer.

The existing `clusters/homelab/apps/media-postgres-recovery/` pattern represents
maintenance through a recovery overlay. Reuse its declared phase separation,
with the stronger node-level fence required by
[[architecture/cluster-topology#Current Worker Recovery|the unchanged-boot worker incident]].
Prepare capture and resume revisions for review **before** entering maintenance.
All deployed repository references remain on `main`.

1. **Prepare inactive recovery resources.** Under
   `clusters/homelab/apps/n8n-postgres/`, declare a retained backup claim,
   bounded capture/verification scripts and Jobs, and narrowly selected network
   rules. Use the n8n Application's existing repository source for maintenance
   route/Deployment changes; never declare a second owner of its Deployment.
   A future `scripts/n8n-recovery-checkpoint.sh` observes exact revisions,
   node/process identity, Job state, and private recovery receipts. Test its
   rejection paths before its first operational use.
2. **Enter a reviewed window.** Commit maintenance responses for editor/API
   and webhook routes, then n8n replicas zero in its Helm values. Inventory and
   fence every possible n8n writer: main, workers, webhook processors, CLI
   sessions, copy jobs, and evicted Pods. Current regular/single-main mode is a
   preflight requirement; queue or external writers require an expanded design.
   Observe graceful process termination, not merely zero Kubernetes Pods.
   Preserve persisted waiting executions; do not clear queues or rewrite
   workflow activation state to manufacture an idle database.
3. **Establish the node fence.** For every possible old writer, require healthy
   authenticated Talos/runtime evidence plus absence of its processes and
   writable data mounts. Otherwise require a confirmed held shutdown, or a
   confirmed changed boot ID followed by those node-side checks. An unreachable
   node or unchanged boot is not proof of termination. Any necessary node
   recovery needs its own reviewed repository path; this plan does not reboot
   nodes. A repo-owned observer must keep the evidence valid from capture start
   through publication. Loss of health or identity aborts the candidate set.
4. **Capture the matched set.** Leave PostgreSQL running; reject unexpected
   application write sessions and concurrent schema/key maintenance. Mount
   `.n8n` read-only and take one PG14 custom database dump plus required role
   metadata without password hashes. Archive the whole cold data tree, including
   configuration, both storage layouts, installed extensions, and legacy SQLite
   files. Preserve ownership, permissions, and links safely; reject links or
   nested mounts escaping the approved tree. Compare complete source inventories
   before/after, verify dump metadata/checksums, and publish one immutable set
   ID atomically only while the node fence still passes. Separate DB/file
   "latest" pointers are forbidden. A checksum validates bytes, not coherence.
5. **Resume the original instance.** After a coherent candidate is sealed,
   confirm capture writers exited at their nodes, then merge the prepared
   replicas-one revision. Restore normal routes only after the same image,
   original claims/config, readiness, and required private application checks
   pass. The restore proof runs separately against the sealed copy, so it need
   not extend routine capture downtime. Until it passes, status is
   **captured, restore unverified**, never a successful recovery drill.
6. **Verify data in disposable storage.** Restore PostgreSQL with the archive's
   own database creation metadata, then restore the matched `.n8n` tree using
   the exact captured n8n image and feature configuration. Permit only the
   local PostgreSQL socket; no production DB/PVC, live Kubernetes Secret mounts,
   ingress, or external egress. The persisted production key inside the matched
   backup is required; never replace it with the current bootstrap Secret.
   Do not launch the n8n server, worker, webhook processor,
   or workflow runner. Check schema/ownership, private source-vs-restored
   inventories, every persisted binary reference and metadata file, legacy/key-ID
   decryption, and waiting-execution data. Preserve all source copies. Passing
   these checks means **data verified, startup unverified**.
7. **Prove isolated startup.** Restore a fresh disposable clone from the same
   sealed set, not the CLI-mutated verification clone. Run the captured n8n
   main image with its restored extensions, storage and feature configuration
   behind the enforced startup boundary below. Require bounded startup and
   readiness proof before reporting **restore verified in isolation**; live
   workflow acceptance remains a separate production gate.

The exact fence-evidence transport and fail-closed publication handshake still
need implementation and review. A static approval file or expired check cannot
stand in for continued node evidence. No automatic cycle should be enabled
while this gate is missing.

## Restore Proof And Failure Handling

**Enforced isolation is a prerequisite to loading real recovery material.**
The current Flannel deployment does not enforce NetworkPolicy; see
[[runbooks/runtime-isolation]]. Declaring deny rules does not establish the
verifier's no-network boundary or the capture Job's PostgreSQL-only egress.
Before either receives real credentials, implement and review an enforced
boundary, then test the exact runtime/security profile with synthetic data:
the verifier must fail connections to other Pods, Services, node/LAN addresses,
public endpoints, and DNS; capture must reach only its declared PostgreSQL
destination and required DNS, with all other tested destinations denied.
Include direct-IP attempts and verify the policy's actual enforcement, not
only expected connection timeouts. Recheck after CNI/runtime changes. This
platform/runtime gate remains open; choosing an enforcer or another isolated
execution boundary is a separate reviewed change. [Flannel policy support][flannel-policy].

Startup needs a **separately declared, enforced loopback-only runtime**. The
pinned HTTP server listens on TCP; the PostgreSQL verifier's Unix-socket-only
launcher does not suffice. Keep PostgreSQL on its private Unix socket and bind
n8n HTTP to loopback inside a private network namespace with no external
interfaces, routes, published ports, ingress, or egress. The probe must run
inside that same boundary. No Pod/host network, host/runtime sockets, live
Secrets or production mounts may be available; only disposable DB/data/scratch
may be written. Preserve the sealed archive outside the application runtime.
Before real data is loaded, prove loopback readiness traffic works and external
IPv4/IPv6, DNS and inbound traffic cannot cross this exact runtime boundary.
Apply the existing enforcement checks to all descendants throughout startup
and shutdown; flags or an unreachable destination are not isolation proof.
The runtime implementation and its synthetic preflight remain open review
gates. [HTTP listener and readiness][abstract-server].

Normal startup can resume waiting/enqueued executions and activate triggers
without an incoming request. Their local effects must stay in disposable
storage and **no external workflow side effects may escape**. Do not deactivate
workflows, erase waiting executions, omit extensions, or change captured feature
flags to produce a passing result. Declare only the necessary isolated DB and
listener address overrides. [Startup][start-command], [wait tracking][wait-tracker].

The startup wrapper must enforce a reviewed hard deadline, require the same
main process to remain alive without restart and return HTTP `200` from
`/healthz/readiness` for a continuous declared observation interval, then stop
and reap every descendant before discarding the clone. Set and test both time
bounds with synthetic fixtures before handling real data; they are not an RTO.
`/healthz` alone is insufficient. Readiness is necessary but does not prove
every workflow activation: also check private startup/extension/storage and
activation results, including asynchronous initialization, and require unchanged
migration inventory. Any unresolved failure or incomplete evidence leaves
**startup unverified**, even with HTTP `200`. If isolation blocks a required
external activation, record that dependency and keep the gate open; never grant
egress to make the drill pass. [HTTP readiness][abstract-server],
[startup activation][start-command], [activation handling][active-workflows].

The pinned `export:credentials --all --decrypted --output=<private-scratch-file>`
command can exercise credential decryption without running workflows. Its
output is plaintext, and some failure branches only log/return. A wrapper must
require a newly created restrictive file, independently validate its complete
ID set and parsed data, capture all CLI logs privately, and remove the output.
Never accept exit code alone or copy decrypted output to the retained backup.
Its base initialization runs database migrations, so use only a disposable
clone with the exact source version and require the migration inventory to
remain unchanged. Feature-enabled key bootstrap must not silently repair a
missing key row and turn an incomplete restore green.
[Credential export][credential-export], [CLI initialization][base-command].

Fixtures must include filesystem binaries plus metadata, a retained waiting
execution, the persisted instance key, legacy and rotated-key ciphertext,
and matching image/config identity. Negative cases must reject a missing blob,
wrong/missing key, omitted historical key row, mismatched DB/file set, corruption,
interrupted capture, stale node evidence, and a silent CLI export failure.
Startup fixtures must also fail for a broken restored extension, unwritable
runtime storage, process exit/restart, readiness timeout and activation failure;
prove that scheduled/resumed fixture workflows cannot reach an external sink.
Checks may compare private counts internally; public logs report fixed stages
and pass/fail only. Keep **captured**, **data verified**, **isolated startup
verified**, and **live workflow accepted** evidence separate. Only the combined
data and startup gates prove an isolated restore. Real callback delivery,
schedules and external credential/provider behavior require separately approved
live workflow acceptance after production restoration.

Capture/verification never overwrites production state. Before any production
restore, fence **all** writers again and restore both components into new
retained claims using completion markers and matched IDs. Retain the previous
pair. After production resumes writing, the old pair is stale: rollback needs
a new coherent checkpoint or a separately accepted data-loss/RPO decision.
An image-only downgrade after database migrations is not a rollback.

## Downtime, Permissions, And Implementation Gates

The live Pod currently has a 30-second termination grace. Upstream defaults to
a 30-second graceful-shutdown deadline, while workflow execution time can be
unlimited. Shutdown stops trigger tracking and waits for active work, but the
deadline can force an unsuccessful exit. No lossless fixed drain time follows
from those defaults. A timed-out or killed process does not satisfy the planned
graceful-checkpoint gate. [Shutdown][base-command], [execution drain][active-executions],
[timeout defaults][generic-config], [execution defaults][executions-config].

Expected unavailability is **drain + cold capture + GitOps transitions + restart**;
webhook senders may not retry, and schedules may miss their window. A proposed
first rehearsal budget is 30 minutes, not a measured RTO or a forced-restart
deadline. Pre-review phase revisions; measure controller/merge delays, drain,
copy, restart, and callback behavior before accepting a recurring window.
If an increased shutdown grace is needed, review that rollout separately;
changing the setting itself replaces the current Pod. Abort/overrun behavior
must preserve the fence and alert the operator, never force a green result.

| Actor | Minimum authority |
| --- | --- |
| Argo | Existing ownership of declared Deployment, routes, PVCs and Jobs; no new backup identity may scale workloads |
| Private observer | Kubernetes get/list/watch on relevant workloads, nodes, claims, Jobs and Applications; authenticated Talos read-only health/process/mount/boot inspection; no Talos mutation |
| Capture Job | Read-only n8n PVC and file-backed DB credential; DB read/dump privileges for required schema/roles, no password hashes or superuser requirement by default; egress only to its PostgreSQL Service and required DNS; write only backup/scratch |
| Verifier Job | Read-only matched backup, including its persisted key; bounded disposable data/scratch; private PostgreSQL socket and, for startup only, reviewed isolated loopback TCP; no live Kubernetes Secret mounts, service-account token, Pod network, or host access |

Both Jobs disable service-account token mounting. Use restrictive archive
permissions, no privilege escalation, non-root IDs, dropped capabilities,
explicit CPU/memory/ephemeral-storage limits and deadlines.
Provision any missing read-only DB permission through a reviewed repository SQL
path; never mount the admin secret as an automatic fallback. Capacity and restore
budgets must be measured before choosing limits. A retained `nfs-default` backup
claim avoids new hardware/provider selection but shares the QNAP failure domain.
Independent encrypted backup storage and recoverable key custody remain open.

Implementation order: (1) exact-version synthetic fixtures, observer rejection
tests, and proof of the enforced network boundary before real data is loaded;
(2) inactive manifests, capture/publication protocol, scoped credentials and
restore verifier; (3) reviewed maintenance rehearsal and recovery evidence;
(4) freshness alerts distinguishing capture, data verification and isolated
startup proof; (5) an explicit cadence/interruption decision. Until then, only
verification of sealed sets may be scheduled. Recurring captures must use the
same reviewed GitOps entry/capture/resume path; a future autonomous maintenance
controller would require a separate ownership, node-fencing, permissions, and
outage design.

[binary-config]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/core/src/binary-data/binary-data.config.ts
[storage-config]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/core/src/storage.config.ts
[blob-manager]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/core/src/binary-data/blob.manager.ts
[pg-dump]: https://www.postgresql.org/docs/14/app-pgdump.html
[instance-settings]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/core/src/instance-settings/instance-settings.ts
[key-manager]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/cli/src/modules/encryption-key-manager/key-manager.service.ts
[cipher]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/core/src/encryption/cipher.ts
[credential-export]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/cli/src/commands/export/credentials.ts
[base-command]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/cli/src/commands/base-command.ts
[active-executions]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/cli/src/active-executions.ts
[generic-config]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/@n8n/config/src/configs/generic.config.ts
[executions-config]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/@n8n/config/src/configs/executions.config.ts
[flannel-policy]: https://github.com/flannel-io/flannel#network-policy
[abstract-server]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/cli/src/abstract-server.ts
[start-command]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/cli/src/commands/start.ts
[wait-tracker]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/cli/src/wait-tracker.ts
[active-workflows]: https://github.com/n8n-io/n8n/blob/5542b8b6419cb6925cca8f11b270c9bfbe09d85e/packages/cli/src/active-workflow-manager.ts
