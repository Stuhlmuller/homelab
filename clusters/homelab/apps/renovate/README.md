# Renovate

Renovate scans Stuhlmuller-owned GitHub repositories at 00 minutes past every
hour, UTC. The `automation` CronJob is initially suspended, and its committed
config uses Renovate's full dry-run mode. The old writer in
`Stuhlmuller/renovate` remains authoritative until dry-run parity is verified
and its entire workflow is removed through a reviewed PR. Only then may a
reviewed homelab change remove `dryRun: 'full'`.

The global policy preserves the existing best-practices, replacements,
OpenSSF, lockfile, vulnerability alert, label, platform-commit, and auto-merge
settings. Repository files still override eligible settings. Autodiscovery
filters to `Stuhlmuller/*`, includes owned forks, skips archived repositories,
and processes repositories without a config file. In the 2026-10-18 baseline,
the owner had eight non-archived repositories, and the existing
`rstuhlmuller-renovate` App installation selected all repositories. The last
observed legacy scheduled run (39092061312) succeeded at 2026-10-18 03:00 UTC.
Its workflow/config commits were `3f5f078000173af86205f04df1559132d3e290f8`
and `2215ff710e3395fe3e1955adf8911e54412dcfc5`, respectively; existing
dependency PRs use author `rstuhlmuller-renovate[bot]`. The current
operator credential could not enumerate the App's accessible repositories;
compare that inventory, App grants, and existing PR author with the first
cluster dry run before cutover. Keep private repository names out of public
reports.

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

The protected credential-transfer workflow in `Stuhlmuller/renovate` writes
the existing App credentials to those exact SSM paths. Apply the temporary
exact-scope transfer role through reviewed IaC before transfer. Verify
ExternalSecret `Ready=True` and target Secret metadata without reading values,
and require its refresh timestamp to follow the transfer receipt. It refreshes
every five minutes so a previously projected placeholder cannot remain stale.
Then retire the temporary write grant before unsuspending the CronJob. The
first full dry run must successfully mint an App token. For rotation, restore
that reviewed grant, transfer new values, wait for a later ExternalSecret
refresh, verify a later Job under the same App, and retire the grant again.

The retained `renovate-cache` 20 GiB `nfs-default` PVC holds Renovate's
datasource, private-package, and repository-extraction caches. It contains
private package metadata, so restrict volume access and
logs. Repository clones and work files use an ephemeral `/tmp` volume. The
cache can be rebuilt; it needs no backup. Argo CD does not prune the PVC. If
it is corrupt, review a desired-state reset and allow the next Job to rebuild
it. Do not delete the PVC by hand. The non-root container has a writable
ephemeral root because the default Renovate image installs package-manager
tools there for lockfile updates. No Service or ingress is exposed.

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
While suspended, confirm the ExternalSecret is Ready, the target Secret exists,
and no Job was created. Then unsuspend only through reviewed GitOps code. Two
scheduled dry-run Pods must prove repository coverage, planned proposals,
unchanged App identity and merge policy, and a cache hit for the same datasource
key across Pod UIDs. A shorter second run alone does not prove cache reuse.
Keep detailed Renovate logs private.

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

Cutover is a two-repository sequence: after dry-run parity and the last old
run, delete the complete legacy workflow including manual dispatch, verify no
nonterminal old run remains, then enable cluster writes through a reviewed
homelab change. For rollback, first suspend or restore full dry-run mode in
homelab GitOps, verify no pending or active write-enabled Job, then restore
the legacy workflow through a reviewed companion PR. The interval between
legacy deletion and first cluster write is a planned no-writer gap.
