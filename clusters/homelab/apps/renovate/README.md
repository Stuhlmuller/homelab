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
not restore writes.

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
same datasource key across Pod UIDs. After a cold canary lookup, inspect
restricted logs from two warm scheduled Pods with distinct UIDs. Confirm the
exact `Returning cached value` marker for namespace
`github-releases-datasource-v2` and key
`https://api.github.com/:Stuhlmuller:renovate` in both. Only this marker is
raised from TRACE to INFO. A shorter second run alone does not prove cache
reuse. The INFO marker includes `namespace` and `key`, which can contain
private repository or package names. Restrict Pod-log access; keep raw records
out of public PRs, issues, and CI output. Publish only aggregate cache-hit
results and distinct Pod UIDs. Remove `logLevelRemap` through a reviewed PR
after evidence is captured and before enabling writes; keep the hourly schedule
and Renovate's normal cache freshness rules.
`scripts/ci/renovate-log-remap-test.mjs` verifies the INFO record and its
metadata against an installed copy of pinned Renovate 44.167.4.

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

A temporary acceptance observer is declared but remains suspended. Once enabled,
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

## Temporary acceptance observer

The separate `renovate-acceptance-observer` CronJob is staged suspended. It
would poll every 15 minutes during the seven-day acceptance window. It mounts
only `renovate-acceptance-ledger`, never `renovate-cache`. It asks GitHub for an
installation token limited to `contents` and `metadata` **read** permissions.
Its own GitHub POST mints that token; datasource clients may POST read-only
GraphQL queries. The observer calls the pinned Renovate image's datasource
implementations directly, bypassing the
package-cache wrapper. Any datasource-local cache is confined to one Pod's
ephemeral `/tmp`; the next poll uses a new Pod. It has no Kubernetes API token
or inbound Service.

Before starting this CronJob, create a reviewed, read-only dependency inventory
from the actual Renovate extraction baseline. Put `inventory.json` on the
private ledger PVC through a reviewed GitOps Job, then run this script's
`seed` mode in that Job while the CronJob remains suspended. The inventory
must record a reproducible `seed`, the extraction commit SHA, every active
datasource class, and each candidate's repository, datasource, package name,
source visibility (`public` or `private`), and optional registry URL/current
value. Mark the controlled release canary; its fixture path is excluded even
if the marker is omitted. The inventory review must prove every active class
and public/private source stratum where present; the script rejects a missing
class but cannot discover an omitted class from a falsified inventory. Private
repository/package identities stay on the volume and out of public reviews.

The seed selects up to five packages per datasource and source-visibility
stratum by SHA-256 of the preregistered seed and dependency key. It writes the
selection once to `/ledger/private/ledger.json` with mode `0600`; the seed stays
private. A second seed refuses to replace it. Check the seed Job's aggregate
counts, then use a
reviewed GitOps change to unsuspend the CronJob. Its first healthy poll sets
the baseline. Later healthy polls record each new version with the previous
healthy request-start time and first presence response time. Failed source
polls stay in the private ledger and mark spanning brackets ambiguous; they do
not advance a bracket. Only counts appear in Pod logs. The `report` mode emits
aggregate sample, stratum, poll-failure, bracket, and ambiguous-event counts; raw brackets stay
on the protected PVC. Do not publish the inventory or ledger.

Start the seven-day clock only after the sample and baseline are verified.
Keep the observer suspended if the inventory, a datasource, private-source
access, or the pinned image's datasource API fails validation. After the
aggregate report is reviewed, erase the private files with a reviewed GitOps
cleanup Job and verify `/ledger/private` is empty. Next remove `Prune=false`
from the PVC manifest through GitOps and verify the live PVC annotation is
gone. Only then remove the CronJob, script, cleanup Job, and PVC manifests
through a reviewed change; verify the PVC is gone. `nfs-default` has
`Retain` reclaim policy and `archiveOnDelete: true`, so the backing PV and
NFS subdirectory can persist after claim deletion; later volume deletion can
archive the directory. Use a separate reviewed storage cleanup path, then
verify the PV and any subdirectory or archive are gone before closing T035.
A PVC reset before the aggregate review destroys acceptance evidence.
