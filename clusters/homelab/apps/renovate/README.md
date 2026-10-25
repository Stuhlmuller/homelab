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
Renovate's `homelab-workloads` Argo project cannot own a PV. In a second
reviewed PR, add `dedicated-cache-pvc.yaml` and a credential-free, read-only
claim-probe Job to Renovate's Kustomization. Verify the claim is bound and the
probe's mounted `df` reports 16–24 GiB from exactly
`10.1.0.2:/renovate-cache`. Keep the live CronJob on `renovate-cache` if the
probe fails. Remove the completed probe through a later reviewed change.
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

A temporary acceptance observer is planned but not yet declared. Once added,
keep it suspended until its private sample is fixed before the seven-day
window. It must poll upstream without the Renovate cache or GitHub writes;
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
old key exists. For rollback, first suspend the cluster CronJob through
reviewed GitOps, verify Argo CD synced and no pending or active Renovate Job or
Pod remains, then use the guarded companion
`scripts/restore-renovate-actions-key.py` from exact reviewed companion `main`
to restore the repository key from SSM. Verify its receipt before restoring the
legacy workflow through a reviewed PR. The interval between legacy deletion
and first cluster write is a planned no-writer gap.
