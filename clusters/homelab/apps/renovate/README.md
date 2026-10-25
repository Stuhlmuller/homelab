# Renovate

Renovate scans Stuhlmuller-owned GitHub repositories at 00 minutes past every
hour, UTC. The `automation` CronJob runs in Renovate's full dry-run mode. The
old writer in `Stuhlmuller/renovate` remains authoritative until dry-run parity
is verified and its entire workflow is removed through a reviewed PR. Only
then may a reviewed homelab change remove `dryRun: 'full'`.

The global policy preserves the existing best-practices, replacements,
OpenSSF, lockfile, vulnerability alert, label, platform-commit, and auto-merge
settings. Repository files still override eligible settings. Autodiscovery
filters to `Stuhlmuller/*`, includes owned forks, skips archived repositories,
and processes repositories without a config file. The 2026-10-19 owner API
inventory had 18 repositories: 10 archived and eight eligible non-archived,
including four private repositories and no forks. The active
`rstuhlmuller-renovate` App installation selected all repositories. The last
observed legacy scheduled run (39193708267) succeeded at 2026-10-19 03:14 UTC.
Its App-token scan started and finished all eight then-eligible owner
repositories, including the four private repositories, and scanned none of the
ten archives; the owner had no forks to exercise live fork handling.
Its workflow/config commits were `3f5f078000173af86205f04df1559132d3e290f8`
and `2215ff710e3395fe3e1955adf8911e54412dcfc5`, respectively; existing
dependency PRs use author `rstuhlmuller-renovate[bot]`. The runner pins that
bot username and Git author so startup needs no account lookup. The legacy
workflow and global config reference no separate private-registry credential
input; the workflow uses only the existing App secrets. The GitHub
organization installation API confirmed on 2026-10-19 that the active App
selects all repositories and has effective repository Checks, Contents, Issues,
Pull requests, Commit statuses, and Workflows write; Metadata and Dependabot
alerts read; and organization Members and Administration read. It lacks
repository Administration read from Renovate's recommended grants. This does
not block discovery, but a repository override using automatic rebasing may
lose branch-protection awareness. The operator credential cannot enumerate the
current installation-token repository list; all-repositories selection, the
owner inventory, and the eight-of-eight legacy App-token scan imply coverage.
Compare actual cluster discovery, repository overrides, and existing PR author
with the first scheduled dry run before cutover. Keep private repository names
out of public reports.

## Credentials and storage

The `renovate` ExternalSecret projects only
`/homelab/renovate/github-app/issuer-id` and
`/homelab/renovate/github-app/private-key` from the `aws-ssm` ClusterSecretStore
into the namespaced `renovate` Secret. The Pod reads `issuer-id` and
`private-key` under `/var/run/secrets/renovate` as read-only files. `config.js`
signs a GitHub App JWT in memory and requests one installation token at Job
start. Neither credential nor token belongs in logs, Pod environment, command
arguments, or the cache. The Pod has no Kubernetes API token. The token must
cover all owner repositories. The Job has a 40-minute deadline and config
requires 55 minutes of token validity at startup; otherwise it fails closed.

The protected credential-transfer workflow in `Stuhlmuller/renovate` wrote the
existing App credentials to those exact SSM paths on 2026-10-19 in run
`39196912858`. Both SecureStrings reached version 2. The ExternalSecret
refreshes every five minutes. It refreshed at 03:56:19 UTC after transfer,
with `Ready=True` and a changed target Secret resource version; no values were
read. The CronJob remained suspended with no Renovate Job.
The operator then removed the temporary transfer role through the reviewed
saved-plan path and verified an IAM `NoSuchEntity` lookup and a fresh no-op plan.
The [operator receipt](../../../../docs/operator-infrastructure.md#renovate-app-credential-transfer-and-role-retirement)
records the checks without credential values. A manual full dry run minted an
App token and finished all eight eligible repositories; scheduled scans must
still prove parity and cache reuse. For rotation, reintroduce the same limited
role through a reviewed change, transfer new values, wait for a later
ExternalSecret refresh, verify a later Job under the same App, and retire the
grant again.

The retained `renovate-cache` 20 GiB `nfs-default` PVC holds Renovate's
datasource, private-package, and repository-extraction caches. It contains
private package metadata, so restrict volume access and
logs. Repository clones and work files use an ephemeral `/tmp` volume. The
cache can be rebuilt; it has no backup. Argo CD does not prune the PVC. The
non-root container has a writable ephemeral root because the Renovate image
installs package-manager tools there for lockfile updates. No Service or ingress
is exposed.

Harbor Docker lookups use the canonical `harbor.stinkyboi.com` TLS name through
the registry-only `traefik-registry` Service at `10.96.0.50:443`. A Pod-local
host alias selects this route without changing cluster DNS or node image pulls.
On 2026-10-19, destination ztunnel rejected the first dry-run Pod's default
service identity at the shared private listener before Harbor received traffic.
The dedicated `renovate` ServiceAccount mounts no Kubernetes token; Istio allows
only its identity to the registry listener on port 9443. That listener exposes
only OCI and token paths. No Harbor credential is configured, matching the old
runner; anonymous lookups can see the public `mirror` project but not private
projects. In dry-run verification, distinguish a transport failure from an
expected authentication denial. Hold writer cutover if an eligible private
package requires a credential. Revert this route change through GitOps if it
breaks registry access.

### Cache failure and recovery

An unavailable claim leaves the Job Pod pending with a mount or scheduling
event. Before GitHub access, the config writes and flushes a 4 KiB probe to
the cache; a full or unwritable claim fails the Job with a storage error. Check
the PVC, Pod events, Job condition, and restricted Job logs before changing
state:

```sh
kubectl -n automation get pvc renovate-cache
kubectl -n automation get pods -l app.kubernetes.io/name=renovate
kubectl -n automation describe pod <renovate-pod>
kubectl -n automation describe job <renovate-job>
```

The `20Gi` request in `pvc.yaml` neither reserves NAS space nor caps this
cache: `nfs-default` does not enforce per-claim size, and its provisioner
cannot resize PVCs. If the backing share is full, suspend `cronjob.yaml`
through a reviewed PR, restore share capacity through a declared path, and
verify the next scheduled Job after resuming. If no declared NAS capacity path
exists, add one before changing live state. Increasing the PVC request will
not restore writes. No verified QNAP `/homelab` capacity-restoration operation
is declared yet. The staged platform `renovate-cache-pv.yaml` and workload
`dedicated-cache-pvc.yaml` define a static PV and new claim for a separate
20 GiB QTS thick volume exported as `/renovate-cache`. Both are absent from
their Kustomizations; verify the NAS volume and export before binding them.
A bounded, isolated tmpfs `ENOSPC` drill can test failure
visibility and later normal PVC use, but cannot prove recovery from an actual
full NAS export. T024/T042 and writer cutover remain blocked on a declared
capacity path and direct recovery evidence.

Renovate 44.167.4 treats missing or malformed package entries as misses and
skips malformed repository cache files; a later run can rebuild both from
upstream. The pinned upstream recovery fixture in
`scripts/ci/renovate-cache-recovery-test.mjs` checks these cases. A full claim
blocks App token minting until capacity is restored. If repeated runs still
fail because the cache tree itself is corrupt, first suspend `cronjob.yaml`
through a reviewed PR and confirm no active Renovate Job remains. Use a
reviewed, temporary GitOps Job that mounts only `renovate-cache`, deletes only
its contents, and has no App credential or cluster API token. Verify that Job
completes, remove it through a second reviewed change, then unsuspend the
CronJob. Open PRs and repository policy remain on GitHub. Do not delete the
PVC or edit NFS files by hand. If the claim cannot mount or the backing share
is full, restore the declared storage path before resuming scans. Record the
failed cycle and verify the next scheduled run and freshness alerts recover.

### Staged dedicated-cache cutover

`clusters/homelab/platform/storage/renovate-cache-pv.yaml` and
`dedicated-cache-pvc.yaml` are outside their Kustomizations and have no live
effect. The target is a separate 20 GiB
QTS thick volume on Storage Pool 1 with one NFSv3 export at
`10.1.0.2:/renovate-cache`, the same four Talos node allow-list and guest
all-squash mapping as `/homelab`, and no snapshots or recycle bin for this
rebuildable cache. A folder under `/homelab` is not an isolated capacity limit.
NFSv3 `sys` and all-squash trust every permitted Talos node for cache
confidentiality; POSIX file modes do not isolate private package metadata
between permitted NFS clients. Keep the node allow-list exact.
No supported repository-owned QNAP volume-creation path exists. The owner
authorized one QTS setup after this reviewed change merges. In QTS Storage &
Snapshots, create only a 20 GiB thick volume in existing Storage Pool 1;
create the `renovate-cache` shared folder on that volume, disable snapshots
and the network recycle bin for this rebuildable cache, and grant NFSv3
read/write access only to the four Talos node addresses in
[`docs/storage-nfs.md`](../../../../docs/storage-nfs.md), with `sys` security
and all-squash to guest. Do not create a pool or change existing exports.
Before GitOps activation, verify in QTS that this is a separate 20 GiB volume,
`showmount -e 10.1.0.2` lists `/renovate-cache`, and the four-node allow-list
is exact. Add only `renovate-cache-pv.yaml` to the `platform-storage`
Kustomization in a reviewed PR and verify its cluster-scoped PV reconciles.
Each activation PR must update `scripts/ci/renovate-cache-capacity-drill-test.py`
to assert that phase's intended Kustomization membership and Job suspension;
its staging assertions deliberately fail after a resource is activated.
The [`platform-storage` stack](../../../../IaC/homelab/us-west-2/apps/platform-storage/stack.hcl)
inherits the [`homelab` AppProject](../../argocd/self-management/appproject.yaml),
which whitelists PVs; Renovate's `homelab-workloads` project cannot own one.
In a second reviewed PR, add `dedicated-cache-pvc.yaml` and the staged
`dedicated-cache-claim-probe.yaml` to Renovate's Kustomization; set the Job's
`suspend` to `false` in that same change. The probe has no GitHub credential
or Kubernetes API token, mounts only the new claim read-only, and denies Pod
network traffic. Verify the claim is Bound and the Job succeeds with its
source, read-only mount, and 16–24 GiB capacity check against exactly
`10.1.0.2:/renovate-cache`. Keep the live CronJob on `renovate-cache` if the
probe fails. Remove the completed probe and its NetworkPolicy through a later
reviewed change.
Suspend the CronJob through a
reviewed PR and confirm Argo CD synced to exact `main` with no active Renovate
Job or Pod. Switch the CronJob claim to `renovate-cache-dedicated` and unsuspend
through a reviewed PR. The first scheduled Pod must mount the new volume,
pass Renovate's write probe, and rebuild the cache from upstream; a later
scheduled Pod must show a cache hit. Retain the old `renovate-cache` claim and
its contents for rollback until the new cache has survived separate scheduled
Pods. Roll back the claim reference through GitOps if the new mount or rebuild
fails.

For a real full-volume drill, first verify the target is the dedicated QTS
volume, then use a bounded, reviewed GitOps Job to fill only that volume and
observe the next scheduled dry-run fail before App token minting. Remove only
the drill filler through a second reviewed Job, verify a write probe, and
observe the following scheduled run reuse the preserved cache. Do not fill
`/homelab`. A genuine cache-capacity incident follows the same suspend,
reviewed cache-only cleanup, write-probe, and resume sequence; never delete
repository state or the PVC.

## Validate and observe

Before merging a consuming image reference, publish the pinned Renovate index
digest through the protected Harbor mirror workflow and verify a complete
authenticated pull. Validate the rendered resource and credential-free token
self-check locally:

```sh
node --test scripts/ci/renovate-config-test.js
kubectl kustomize clusters/homelab/apps/renovate
```

Use the Terragrunt, static, Conftest, and protected private-plan gates in
`specs/004-run-renovate-in-cluster/quickstart.md` before live reconciliation.
Before activation, the ExternalSecret was Ready, the target Secret existed,
and the CronJob was suspended. A manual full dry run finished all eight eligible
repositories without a new bot PR, but its Harbor lookups failed before the
registry-only route was deployed. It does not prove scheduled operation or
cache reuse. Scheduled dry-run Pods must prove repository coverage, planned
proposals, unchanged App identity and merge policy, and a cache hit for the
same datasource key across Pod UIDs. The completed canary proof used the exact
`Returning cached value` marker for namespace
`github-releases-datasource-v2` and key
`https://api.github.com/:Stuhlmuller:renovate` in restricted logs from two
warm scheduled Pods with distinct UIDs. A shorter second run alone does not
prove cache reuse. The temporary INFO remap has been removed because its
`namespace` and `key` fields can identify private repositories or packages.
Keep raw records out of public PRs, issues, and CI output; publish only
aggregate cache-hit results and distinct Pod UIDs. Future cache checks need
scoped TRACE or a mock upstream counter. Keep the hourly schedule and
Renovate's normal cache freshness rules.

On 2026-10-19, the 19:00 and 20:00 scheduled Pods had distinct UIDs and each
hit that exact cached key. After the protected v0.0.2 release at 20:20 UTC, the
21:00 full dry run kept the cache hit and gained one branch-commit proposal for
the public canary; its four other proposals were unchanged. Renovate's pinned
full dry-run path stops before creating a new PR, so no create-PR marker is
expected. The
[parity receipt](../../../../specs/004-run-renovate-in-cluster/dry-run-parity-receipt.md)
records the aggregate evidence. A manual cluster Job created the public canary
record at 05:13 UTC after v0.0.1 was published; historical Job and Pod
metrics confirm it mounted the retained PVC. T022 is complete. Real PR creation
and policy remain gated by T031.

Read-only status checks:

```sh
kubectl -n argocd get application renovate
kubectl -n automation get externalsecret renovate
kubectl -n automation get cronjob renovate
kubectl -n automation get jobs -l app.kubernetes.io/name=renovate
kubectl -n automation get pvc renovate-cache
```

A failed Job is covered by the existing Job alert. Renovate-specific alerts
cover a missed start, a cycle with no success by its deadline, and a missing
CronJob. For a failure, inspect Job
conditions, ExternalSecret readiness, restricted logs, and the next scheduled
cycle. Correct desired state in git; do not patch or restart a live Pod.

For per-repository failures, correlate restricted `ERROR`/`FATAL` records and
their repository tags with the final repository summaries. Pinned Renovate can
log `Repository finished` with `done`/`exitCode 0` after a datasource lookup
error, then exit the overall Job nonzero for retained error records. Do not
treat a final per-repository processing summary alone as an error-free scan.

The protected missed-slot drill produced no 03:00 UTC Job, and
`RenovateHourlyCycleMissing` fired at 03:20:47 UTC. The reviewed recovery
restored hourly desired state at 03:35:11 UTC. The unsuspended CronJob created
Job `renovate-29874480` at 04:00:00 UTC; a read-only Prometheus check at
04:00:38 UTC found the missed-cycle rule inactive with no `ALERTS` series.
That Job succeeded at 04:20:23 UTC using Pod UID
`dd063320-8d27-493e-8c62-104aadbb6140`: eight repository starts and
finishes, 124 dry-run markers, one exact public canary cache hit, and zero
error headers, lookup errors, or mutex timeouts. Argo CD was Synced/Healthy
at main `90fc7761618c43a9f120130d584dd7ae4eea0da5`. T045 is complete;
cache-fault recovery under T024/T042 remains open.

The temporary acceptance observer is staged suspended. Keep it suspended
until its private sample is fixed before the seven-day window. It must poll
upstream without the Renovate cache or GitHub writes;
its separate protected ledger retains private release brackets. Publish only
aggregate results, then erase the ledger and retire its Job and claim through
reviewed GitOps. Report a controlled canary separately from natural releases.

Cutover is a two-repository sequence: after dry-run parity and the last old
run, delete the complete legacy workflow including manual dispatch and verify
no nonterminal old run remains. From exact reviewed companion `main`, run its
guarded `scripts/retire-renovate-actions-key.py` and require a current receipt
that the SSM values and later ExternalSecret projection are ready, no same-name
organization or environment secret exists, the repository Actions private key
is absent, and old runs are drained. Then enable cluster writes through a
reviewed homelab change. Historical workflow revisions can be rerun while the
old key exists. For rollback, suspend the cluster CronJob through reviewed
GitOps, verify exact Argo CD sync and no pending or active Renovate Job or Pod,
then repair or revert the same cluster runner through reviewed desired state.
Before the first successful write-enabled Job, return to full dry-run or keep
the CronJob suspended and record the no-writer gap. Keep the old Actions key
absent. Restore the legacy workflow only after a fresh credential-free probe
from a GitHub-hosted runner proves its Harbor Docker datasource route, the
cluster stays drained, and guarded companion key restoration from exact
reviewed `main` yields a verified receipt. The workflow still needs a separate
reviewed PR. The interval between legacy deletion and first cluster write is
a planned no-writer gap.

## Temporary acceptance observer

The acceptance ledger is staged as a dedicated 64 GiB static Talos-local PV at
`/var/lib/renovate-acceptance-ledger` on `acer`. The StorageClass and PV are in
`clusters/homelab/platform/storage/renovate-acceptance-ledger-platform.yaml`;
the namespaced claim is in `acceptance-ledger-pvc.yaml`. Neither file is in its
Kustomization yet. Renovate's `homelab-workloads` Argo project cannot create
cluster-scoped storage. First reconcile the class and PV through a reviewed
`platform-storage` change and verify their identities. Then bind the claim
through a separate reviewed Renovate change and verify it reaches `Bound`.
Every acceptance worker has
an `acer` node selector; the PV has the same node affinity. The shared QNAP
NFS export squashes clients to one guest identity and cannot enforce private
ledger ownership, so it must not hold the sample, reports, review input, or
receipts. Only after the claim binds, run the suspended
`renovate-acceptance-ledger-init` Job through reviewed GitOps. It refuses a
nonempty path and sets the volume root to UID/GID 12021, mode `0700`.
Verify the PVC is bound to the local PV and the init Job succeeded before
activating any acceptance worker. A node loss, failed poll, or missing
15-minute slot makes the seven-day window inconclusive; restart from a newly
reviewed private sample and empty ledger after the node recovers.

The local PV's capacity is advisory for a hostPath. Before activation, verify
`acer` is Ready and has at least 80 GiB free on its node filesystem. A
read-only kubelet check on 2026-10-24 showed 412 GiB available. The proof
reader bounds each report to 128 MiB and the set to 192 hourly reports. The
runner directs the raw report to a separate 128 MiB memory-backed volume,
copies it to the ledger only after success and validation, and caps its
streamed diagnostic log at 128 MiB while Renovate runs. Thus the
seven-day raw report/log ceiling is 48 GiB, leaving room for the ledger and
evidence in the declared 64 GiB size. If measured reports exceed those bounds
or node free space falls, keep the CronJobs suspended and resize through
reviewed desired state before starting the window.

### Hourly schedule acceptance (SC-001)

`scripts/renovate-acceptance-schedule.py` computes an offline SC-001 report
from a private, credential-free `slots.json` and protected source files. It
does not query Kubernetes, start the CronJob, or produce the source evidence.
The input needs `schema: 1`, hour-aligned UTC `windowStart` and `windowEnd`
exactly seven days apart, and one record for **each** of the 168 planned UTC
hours, including missed and excluded slots. Each record needs `slotAt`,
`collectedAt` at least one hour later, a `collection` object with a relative
`evidence/<name>` source and SHA-256, and a `runs` array. Each scheduled run
needs distinct Kubernetes `jobUid` and `podUid`, actual
`jobStartedAt`, `finishedAt`, and `phase` (`succeeded` or `failed`). A run may
have `discoveryCompletedAt` from the restricted Renovate discovery log and an
optional `discoveryStartedAt` only when an exact discovery-start marker exists.
An explicit optional `exclusion` needs `kind` (`maintenance`, `cluster-outage`,
`github-outage`, or `registry-outage`), nonempty observed `impact`, a
`reviewedAt` time after that hour, and its own evidence source and SHA-256.
The referenced files must be unique regular mode `0600` JSON files in a mode
`0700` `evidence/` directory beside the mode `0600` input. Each has
`{schema:1, kind, slotAt, claim, material}`. A `slot-collection` claim is the
exact `collectedAt` and `runs` for its slot; a `slot-exclusion` claim is the
exact exclusion `kind`, `impact`, and `reviewedAt`. `material` is a nonempty
private source object. Hash and claim binding detect missing, reused, or
changed files, but independent review must establish that the source material
is authentic and exhaustive.

The collector ServiceAccount, read-only Role/RoleBinding, and API-only
NetworkPolicy are in Kustomize while
`acceptance-schedule-collector-cronjob.yaml` remains suspended and outside it.
Merge this protected prerequisite first. Before a separate reviewed activation
change adds and unsuspends the CronJob, verify Argo CD synced the prerequisite
revision and read back the collector ServiceAccount, Role, RoleBinding, and
NetworkPolicy in `automation`; confirm the policy selects no current Pod and
has only the expected API endpoints. The collector must not start until those
objects exist. After the local ledger binds, activate the CronJob and verify
its first Job succeeds before starting the seven-day clock.
The collector runs at :05, :20, :35, and :50 UTC. Its dedicated ServiceAccount
can get only the Renovate CronJob, list Jobs/Pods in `automation`, and read Pod
logs there; it has no write verb, GitHub App key, or production cache mount.
Its deny-all policy permits only the Kubernetes API service VIP
`10.96.0.1:443` and Talos control-plane endpoint `10.1.0.199:6443` (for
post-DNAT enforcement). The client connects to the VIP with the API DNS name
for certificate validation and needs no DNS egress. Confirm these exact
endpoints through a read-only check before activating the policy; a changed
API address needs a reviewed update.

Every successful collection records the CronJob schedule and the currently
retained Job/Pod controller UIDs, scheduled-hour annotations, conditions, and
timestamps before Kubernetes prunes older Jobs. It keeps immutable, timestamped
raw logs and snapshots under `/ledger/private/schedule/` with mode `0600`
files and `0700` directories; each log is capped at 8 MiB. Five distinct
versions for each of 168 hourly Pods use at most 6.6 GiB, leaving room beside
the 48 GiB report/log ceiling on the 64 GiB ledger. Oversized logs, API/list
gaps, or a missing terminal log fail collection; resize through reviewed
desired state before restarting the window if the cap proves too small.
Collector Pod logs contain only counts. Raw logs can contain private repository
or package names and must never be published.

The pinned Renovate 44.167.4 [global start log](https://github.com/renovatebot/renovate/blob/44.167.4/lib/workers/global/index.ts#L145-L200)
precedes configuration parsing and platform initialization, so it is not an
owner-discovery start. The [autodiscovery INFO log](https://github.com/renovatebot/renovate/blob/44.167.4/lib/workers/global/autodiscover.ts#L40-L82)
follows `platform.getRepos`; completion within 15 minutes proves discovery
began on time. A later completion without an exact start marker is unknown.
Compare full Job start/end intervals for overlap. A failed Job with no
discovery marker belongs in private source material, with no invented start.
Every slot's collection hash must bind the exhaustive Job/Pod and log snapshot;
an exclusion file must contain the outage or maintenance interval and its
impact on that hour. Prometheus' retained `kube_job_created` and
`kube_pod_container_state_started` history can corroborate timing, but cannot
replace logs or complete collection receipts. Keep the source material and
full slot input on the protected ledger until independent review and reviewed
cleanup. Missing collector cadence, identity, timing, or outage evidence makes
SC-001 inconclusive.

After a complete window, run
`python3 -I scripts/renovate-acceptance-schedule-assemble.py --source
<absolute-private-schedule-dir> --window-start <UTC-hour> --output
<new-private-output-dir>` offline. The assembler requires all 673 quarter-hour
snapshots from the first :05 through the next :05 after the seven-day window,
the same CronJob UID/generation and exact hourly UTC schedule, `Forbid`, a
900-second start deadline, and three retained Jobs per result. It verifies
every referenced immutable log digest and discovery marker, and cross-checks
the CronJob's last scheduled hour against captured Jobs. A terminal Job
with no global Renovate marker can be recorded as a private prestart failure
and an empty run; a Job that started Renovate without a discovery-completion
marker makes assembly inconclusive. It creates `slots.json` and one hashed
claim-bound source file per planned hour, all mode `0600`, in a new mode `0700`
directory. Missing, duplicate, late, changed, or unsafe captures fail closed;
the output is never placed in git. Reviewed outage/maintenance exclusions
need separate private receipts before the evaluator can subtract those hours.

For the acer-local ledger, the staged
`acceptance-schedule-assemble-job.yaml` and its deny-all
`acceptance-schedule-assemble-networkpolicy.yaml` are the declared execution
path. The policy is in Kustomize and selects no current Pod; verify it has
reconciled before activating the Job. The Job remains outside Kustomize,
suspended, with an invalid UTC window-start placeholder. After every
acceptance writer is suspended and drained, set the exact reviewed start hour
and activate the Job through a reviewed GitOps change. The pinned Python image
reads snapshots and logs through a read-only subPath, writes only below the
collector-created
private `assembled/` subPath, mounts no App key or cache, and has no Kubernetes
token or network egress. It logs aggregate counts only; inspect the private
`assembled/seven-day/slots.json` and claim files through the reviewed ledger
path. The assembler already invokes the evaluator before publishing the
output, so a separate in-cluster evaluator Job is unnecessary.

Run `python3 -I scripts/renovate-acceptance-schedule.py
<absolute-private-slots.json>` offline after the window. Its aggregate JSON
reports planned, excluded, denominator, timely starts (at most 15 minutes),
proven late starts, unknown starts, missing runs, failed runs, duplicate cycles,
and overlaps. The no-overlap check uses full Job start-to-finish intervals,
including excluded slots. A missing run in an otherwise complete slot counts
against the 95% threshold; missing slot evidence, unknown starts, failed runs,
or an all-excluded window are
`inconclusive`. Overlap or duplicate cycles fail the criterion even if the
timely rate reaches 95%. Exit codes are 0 for `review-required`, 1 for
`criteria-not-met`, and 2 for `inconclusive`. `review-required` is a numeric
result only: a private reviewer must verify the source files came from the
read-only producer, cover all 168 hours, and justify each exclusion before
claiming SC-001 acceptance. The staged observer does not supply these hourly
writer-run receipts.

The separate `renovate-acceptance-observer` CronJob is staged suspended. It
would poll every 15 minutes during the seven-day acceptance window. It mounts
only `renovate-acceptance-ledger`, never `renovate-cache`. It mounts only the
separate `renovate-acceptance` App Secret and asks GitHub for an installation
token limited to `contents` and `metadata` **read** permissions. The App's
installation grants must also be read-only; `readToken()` rejects a write grant.
Its own GitHub POST mints that token; datasource clients may POST read-only
GraphQL queries. The observer calls the pinned Renovate image's datasource
implementations directly, bypassing the
package-cache wrapper. Any datasource-local cache is confined to one Pod's
ephemeral `/tmp`; the next poll uses a new Pod. It uses the dedicated no-token
`renovate` ServiceAccount and Pod-local registry route; it has no Kubernetes API
token or inbound Service.

`acceptance-primary-report-patch.yaml` is staged outside Kustomize. After the
private ledger claim is Bound, a reviewed GitOps change can add this patch to
the existing hourly CronJob. It runs Renovate once, with the same production
App token, cache, and dry-run or writer policy, and adds pinned Renovate
44.167.4's experimental `reportType: file`. The report contains extracted
`packageFiles`, lookup updates, and branch results such as `prNo`, `result`,
and `prBlockedBy`. The wrapper sets umask `077`, captures bounded private
logs and the report under a Pod UID, then seals a hash receipt only after
Renovate exits successfully. A failed run, missing report, or malformed report
creates no success receipt. Restricted primary Pod logs retain Renovate's
per-repository outcomes and failure details for the operator and schedule
collector; the wrapper also keeps a bounded private copy on the ledger.
Never publish those logs or the raw report. The existing writer key remains
mounted only as a Secret file and is not copied to the ledger. The local
ledger volume constrains the hourly Pod to `acer`. Before starting the
seven-day window, verify memory
headroom and two report-enabled scheduled Jobs on that node, including
completion before the 40-minute deadline, no restarts or MemoryPressure, and
the expected hourly alerts. If this preflight fails, remove the patch through
a reviewed PR, verify Argo CD sync to that main commit, and let existing Jobs
drain before the next ordinary hourly scan. Keep the ledger for diagnosis.

The report is a candidate extraction and policy-outcome source, not a verified
acceptance sample. Its API is experimental. The inventory Job still reads the
repository cache; private review input supplies source visibility and policy
evidence. There is no separate hourly report scan: the staged PR proof CronJob
at :55 reads only a successfully sealed primary-run report. Its one-shot Job
variant remains omitted and suspended. A reviewed GitOps change must activate
the primary report patch and PR proof CronJob only after the sample, App grants,
ledger capacity, and private review are checked.
The proof worker binds an exact sampled package, file, and version to a sealed
report. A single `not-scheduled` or `needs-pr-approval` branch result becomes a
private policy-deferral receipt timestamped at report completion. Other branch
results establish eligibility but require a verified proposal; errors remain
unknown. The worker retains the matching branch material for private review.
GitHub PR `created_at` is context only, since a later synchronize can add a
version. Missing or conflicting proof stays unknown.

`acceptance-pr-proof-job.yaml` stages a read-only GitHub proof path. It is
omitted from Kustomize and suspended. It verifies a pinned report and private
hash receipt, matches an exact sampled package, file, and version to one
Renovate PR number, then reads that PR and its complete GitHub file diff with
a read-scoped App token. A matching added line must contain both the package
and version. It requires GitHub's response clock to agree within one minute.
The worker reads the PR again after fetching all changed files and discards
proof if its head, file count, or state changed. An open PR uses the read time
plus that minute as a conservative proposal **upper bound**. A GitHub-confirmed
merged PR uses `merged_at` as its bound; a closed unmerged PR is not proof.
It retains a bounded 8 MiB private snapshot of both PR reads and the changed
file patches, then writes the hashed outcome receipt to the
ledger; Pod logs contain counts only. Reads more than four hours after the
last-absent bound, missing patches, and ambiguous PR matches remain unknown.
PR `created_at` is retained only as context. A proposal bound after four
hours remains a late outcome. The seven-day window needs enough protected
ledger capacity for the primary reports and PR proof receipts.

Before starting this CronJob, freeze a private inventory from the pinned
Renovate image's actual repository-extraction cache. Full dry-run skips cache
persistence, so this requires a successful later write-enabled scan. The
`acceptance-inventory-job.yaml` Job is deliberately omitted from Kustomize and
has `suspend: true`; merging this source cannot start it. It uses the same
no-token `renovate` ServiceAccount and Pod-local registry route. Its cache mount
is read-only and targets `renovate-cache-dedicated`; verify that the live writer
CronJob uses this same claim before activating the Job. It writes only to the
separate protected ledger. Activate it
through a reviewed GitOps change only after the
App transfer, write cutover, and private review input are ready.

Deliver the private review input once with the repository-owned
`scripts/renovate-acceptance-review.py` command from clean, signed current
`main`. Keep the source JSON outside git as an owner-only mode `0600` file.
The command creates only the fixed, immutable
`automation/renovate-acceptance-review` Secret and verifies readback without
printing values. Its `review.json` key mounts only in the omitted, suspended
inventory Job. That Job freezes a mode `0600` copy owned by UID 12021 on the
dedicated acer-local ledger at `/ledger/private/review.json`; the directory has
mode `0700`. The input contains a fixed seed, UTC-hour `windowStart` and
`windowEnd` exactly seven days apart, the pinned image digest and `config.js`
SHA-256, every non-archived
owned repository's default branch, current head SHA, Renovate cache SHA-512 and
extraction config hash, plus one decision for **every** extracted dependency.
Each decision uses the SHA-256 key returned by `candidateKey(repository,
baseBranch, manager, packageFile, index, dependency)` in
`acceptance-inventory.js`. A sampled decision needs a canonical HTTPS
`registryUrl`, `public` or `private` **source** visibility, and private
visibility/policy evidence references. An excluded decision needs a reason and
private policy evidence. When its extraction has a datasource, it also needs
source visibility and private visibility evidence. The input also needs an
independent owner-inventory receipt (`ownerInventory.repositories`, SHA-256,
source, and a verification time
within one hour) and `expectedStrata` counts for every non-canary extracted
datasource × source-visibility pair, including excluded rows. At least one
dependency in each such stratum must remain selected. The Job compares these
with App-visible repositories and reviewed extraction decisions. Repository
visibility is not source visibility;
rate-limited or failed anonymous registry checks are unknown. Never publish
the review file or private package names.

The Job verifies the pinned cache-v13 Brotli payload and SHA-512, every
extraction row's review decision, exact current GitHub repository inventory and
per-repository default-branch SHA, one canonical registry URL, and the mounted
config/image identity. A missing repo, unknown visibility/policy, stale cache,
ambiguous registry, missing selected stratum, or mismatched declared stratum
fails before seeding. It atomically creates one `ledger.json` with the full
private inventory and
provenance embedded, mode `0600`, and logs counts only. A retry after an
interrupted write can safely complete; it will not replace a frozen sample.
The reviewed window must begin after seeding; an already-started window fails.
Suspend the main Renovate CronJob through GitOps and verify no active Job while
freezing this baseline. Keep
the observer suspended until a private reviewer checks the full eligible
datasource × source-visibility strata and source evidence. The cache is
pre-lookup, so evidence references in `review.json` need independent effective
policy and registry-access verification; the Job alone cannot prove them.

The private input delivery path is declared, but independent owner inventory,
source-visibility, and effective-policy receipt production and review remain
open. Keep the Job omitted/suspended until those inputs and the first
write-enabled extraction cache are ready. Do not place files on the ledger with
an ad hoc live command. A review larger than 900 KiB needs a new reviewed
delivery contract before seeding; this path does not split or truncate it.

After the private source review is complete and the seeding change is ready,
deliver the file shortly before reviewed GitOps activation so the owner
inventory receipt remains within its one-hour validity window:

```sh
python3 -I scripts/renovate-acceptance-review.py install \
  --expected-sha <current-main-sha> --private-file <absolute-private-path> --execute
```

The command requires the homelab API endpoint and never echoes the JSON. A
failed inventory Job keeps the Secret for diagnosis. If a corrected input is
needed, first verify the Job is suspended or terminally failed, then run
`retract --expected-sha <current-main-sha> --execute` from current signed main
before a new `install`. Retraction changes only that Secret; an already frozen
ledger needs a separate reviewed reset. After the inventory Job succeeds and
its aggregate receipt is reviewed, retire the transient Secret:

```sh
python3 -I scripts/renovate-acceptance-review.py retire \
  --expected-sha <current-main-sha> --execute
```

The seed first selects one deterministic repository for each upstream datasource,
package, and normalized registry URL, rejecting conflicting visibility for the
same source. It then
selects up to five packages per datasource and source-visibility stratum by
SHA-256 of the preregistered seed and dependency key. It writes the
selection once to `/ledger/private/ledger.json` with mode `0600`; the seed stays
private. The exact reviewed window is frozen with it. A second seed refuses to
replace it. Check the seed Job's aggregate
counts, then use a
reviewed GitOps change to unsuspend the CronJob. Its first healthy poll sets
the baseline at the reviewed `windowStart` slot. Later healthy polls record
each new version with the previous
healthy request-start time and first presence response time. Failed source
polls stay in the private ledger and mark spanning brackets ambiguous; they do
not advance a bracket. Only counts appear in Pod logs. The `report` mode emits
aggregate sample, stratum, poll-failure, missed-slot, bracket, and ambiguous-event
counts; raw brackets stay on the protected PVC. Do not publish the inventory or
ledger.
The final SC-002 report requires all 673 healthy quarter-hour slots from
`windowStart` through `windowEnd`, inclusive. These bounds cover exactly 168
hourly UTC slots and must match the SC-001 schedule assembler's reviewed start.
Polls and release brackets entirely outside the bounds do not enter the
denominator. A bracket crossing either boundary makes SC-002 inconclusive.
The aggregate prints the frozen bounds and counts missing slots across them.

For the offline SC-002 report, keep `outcomes.json` as a mode `0600` regular file
beside the ledger on the protected PVC. Bind it to `ledger.inventorySha256`, set
`schema: 1`, and provide `receipts` keyed by the sampled item's SHA-256 `key`
and exact observed `version`. Each receipt needs an `eligibility` status:
`eligible`, `policy-ineligible`, `excluded-outage`, or `unknown`. Receipt
eligibility evidence has a `source` path under `evidence/`, its exact SHA-256,
and a `verifiedAt` time;
policy-ineligible adds a policy `reason`. An excluded outage or maintenance
also needs an `exclusion` with `reason` (`source-outage`, `github-outage`, or
`maintenance`), `startAt`, `endAt`, an `affectedAt` time within both that
interval and the event's four-hour window, a nonempty `impact` describing the
affected scheduled lookup, write, or maintenance attempt, `source`, SHA-256, and
`verifiedAt`. Eligible
events may have an `outcome` with `kind` (`proposal` or `deferral`), `at`, private
`source`, SHA-256, and `verifiedAt`; a deferral also needs its policy `reason`.

The `/ledger/private/evidence` directory must have mode `0700`; each referenced
JSON file must be a mode `0600` regular file. Its envelope is `{schema:1, key,
version, kind, claim, material}`: `key` and `version` match the exact receipt,
`kind` is `eligibility`, `outcome`, or `exclusion`, `claim` is the matching
receipt field without `source` and `sha256`, and `material` is a nonempty private
source object. A missing file, mismatched hash, or mismatched envelope makes
the report inconclusive. The file binds a claim to material but does not prove
that GitHub or a package registry supplied it; independent reviewed production
and verification are required.

The report joins exact events, counts eligible events without an outcome in the
denominator, and measures four hours from the conservative `lastAbsent` bound.
It emits only aggregate counts and a rate. Unknown eligibility, incomplete
evidence fields, missing eligible outcomes, ambiguous brackets, or fewer than
ten eligible natural releases
make the result inconclusive. Below 95% on-time gives `criteria-not-met` using
integer counts; the displayed rate is floored to two decimals. The best script
status is `review-required`: locally bound receipts alone cannot prove their
GitHub PR or restricted policy-log source. A reviewed
private receipt-production and independent source-verification path remains a
gate before any SC-002 acceptance claim; do not commit private receipt content
or inject it through an ad hoc live command.
The staged PR verifier checks an exact version in a GitHub diff and uses its
first read time as the timing upper bound. The report worker binds explicit
schedule or PR-approval deferrals to the sealed report completion time. A
private reviewer must still check the stored material and effective policy.
Each sealed report receipt records the SHA-256 of its mounted production
`config.js` policy. The deny-all
`acceptance-source-review-networkpolicy.yaml` reconciles before
any source-review Job. Verify it exists in `automation` after Argo CD sync;
then, after every acceptance writer is suspended and drained, activate the
staged `acceptance-source-review-job.yaml` in a separate reviewed GitOps
change. It mounts the ledger read-only and has no GitHub App key, Kubernetes
token, or network egress. It replays each eligible receipt
against the exact hashed raw report and stored GitHub PR snapshots, and checks
that the report policy hash matches the frozen private review input. Its Pod
logs contain only aggregate source-link counts. A mismatch or missing raw
source makes the report inconclusive. The replay proves internal consistency;
an independent human must still verify the owner inventory, source visibility,
effective repository policy, GitHub source authenticity, and each excluded
interval before accepting an SC-002 result. Keep the ledger intact and the
cleanup Job suspended until that review is recorded.
`review-required` requires 673 contiguous healthy 15-minute polls; missing
slots or node loss force `inconclusive`. Separately verify excluded intervals,
hourly runner slots, and reviewable proposal or policy-deferral sources before
publishing acceptance.

Preregister the seven-day window after sample review. Its first healthy poll
establishes the baseline; a failed start requires a new reviewed window.
Keep the observer suspended if the inventory, a datasource, private-source
access, or the pinned image's datasource API fails validation. After the
seven-day window, remove the primary report patch through reviewed GitOps and
verify the hourly writer uses its original config and no ledger mount. Drain
all report-enabled Jobs before touching the ledger. Suspend and drain the
observer, inventory, PR-proof, and schedule-collector acceptance writers;
verify none of their Jobs or Pods remains pending or active. Activate the
staged read-only
`acceptance-source-review-job.yaml` only after that freeze. Activate the staged
`acceptance-final-report-job.yaml` through a separate reviewed change after
source replay and writer drainage. Verify the pre-reconciled deny-all
`acceptance-final-report-networkpolicy.yaml` exists in `automation` before
that activation. The final Job has no App key, Kubernetes token, or network
egress and mounts the protected ledger read-only. Its
`report` mode reads the frozen sample and private outcomes and prints only
aggregate counts. Review the source evidence and final report. Compare the
final report's `ledgerSha256` with the last observer poll digest; a mismatch
means the report is stale and must be regenerated and reviewed. The digest is
safe to retain in the public activation change; never publish private files.
A missing or failed final report keeps cleanup suspended.

`acceptance-ledger-cleanup-job.yaml` is deliberately suspended and outside
`kustomization.yaml`. In a reviewed activation PR, replace
`REPLACE_WITH_REVIEWED_LEDGER_SHA256` with that exact final 64-character digest,
set `suspend: false`, and add the Job to Renovate's Kustomization. It mounts
only the acceptance ledger PVC, has no Kubernetes token or App credential, and
will refuse deletion if the reviewed hash, mount, ownership, private directory,
or retry marker is wrong. It removes only `/ledger/private`, recreates it empty,
and leaves a digest marker at `/ledger/.renovate-acceptance-cleanup-<digest>` so
a reviewed retry can finish after an interruption. A failed guard leaves the
ledger intact; investigate through a new reviewed change rather than altering
the Pod or files directly.

Verify the Job has `Complete=True` and its restricted log contains exactly the
`private-ledger-empty` result; the Job checks the recreated directory is empty
before logging success. Keep all acceptance writers suspended during this check.
Next remove `Prune=false`
from the PVC and PV and `Delete=false` from the PV through their respective
GitOps Applications; verify the live annotations are gone. Remove the CronJob,
script, init/cleanup Jobs, and PVC from Renovate first, then remove the PV and
local StorageClass from platform-storage through reviewed changes; verify the
claim and PV are gone.
The retained local PV does not erase its hostPath on deletion. Use a separate
reviewed exact-path storage cleanup on `acer` and verify
`/var/lib/renovate-acceptance-ledger` has no retained files before closing
T035. This later hostPath cleanup also removes the Job's digest marker; the
Job itself never touches the backing path directly.
Remove the suspended proof CronJob, one-shot Job manifests, inventory Job,
report patch, and acceptance scripts through the same reviewed GitOps change.
Prune the acceptance ExternalSecret and target `renovate-acceptance` Secret
through reviewed desired state and verify both absent. Obtain explicit owner
authorization/handoff before deleting the dedicated acceptance App in GitHub
owner Developer settings; verify its recorded App ID is absent from the
installation list. Remove only the two
`/homelab/renovate/acceptance/github-app/` SSM names through a reviewed
`IaC/live/aws-ssm-parameters` saved-plan PR and verify both absent. Keep the
production `renovate` App and Secret intact.
A PVC reset before the aggregate review destroys acceptance evidence.
