<!-- markdownlint-disable MD013 -->
# Research: Run Renovate in the Homelab

## Decision 1 — Preserve the current runner's identity and policy

**Decision**: Reuse the existing Renovate GitHub App and migrate the committed global configuration from [Stuhlmuller/renovate](https://github.com/Stuhlmuller/renovate/blob/main/.github/renovate-global.js) into the homelab workload. Preserve its best-practices, replacement, security, labels, lockfile, vulnerability-alert, platform-commit, and daily auto-merge settings. Keep each repository's own configuration effective.

**Rationale**: The [current workflow](https://github.com/Stuhlmuller/renovate/blob/main/.github/workflows/renovate.yml) uses that App and runs daily at 00:00 UTC. The owner explicitly chose to preserve auto-merge. Keeping the App identity protects existing PR continuity; branch protection remains authoritative. Renovate's [configuration precedence](https://docs.renovatebot.com/config-overview/) merges repository config after global config.

**Alternatives considered**: A new bot identity would risk duplicate PRs and different permissions. Disabling auto-merge would change current behavior. A central config that ignores repository files would violate the clarified spec.

## Decision 2 — Discover the owner hourly, including config-free repositories

**Decision**: Use one hourly Kubernetes CronJob with non-overlap. In self-hosted config set GitHub platform, autodiscovery, an owner-path filter for Stuhlmuller, onboarding disabled, and repository config optional. Retain a shared committed global policy so config-free repositories receive update PRs. Enable fork processing to cover owned forks. Archived repositories are skipped; missing App access to an otherwise eligible owned repository blocks cutover.

**Rationale**: [Renovate's Kubernetes example](https://docs.renovatebot.com/examples/self-hosting/) uses an hourly CronJob with Forbid concurrency. Its [self-hosted options](https://docs.renovatebot.com/self-hosted-configuration/) specify that autodiscovery sees accessible repositories, owner-path filters limit the set, and optional config with onboarding disabled processes repositories without a file. [Fork processing](https://docs.renovatebot.com/configuration-options/#forkprocessing) is otherwise skipped in autodiscovery. Recent daily workflow runs took about 5–10 minutes, leaving headroom for hourly scans; the cluster run must still prove the actual duration.

**Alternatives considered**: A static repository list would miss newly owned repositories. Separate per-repository jobs add coordination and cache contention. The default required-config setting would leave config-free repositories idle.

## Decision 3 — Persist lookup cache on one protected PVC

**Decision**: Put Renovate's cache directory on a retained NFS-backed PVC; enable repository extraction cache and private-package caching. Leave datasource soft/hard TTLs at Renovate defaults. Let downloaded-tool cache use its default subdirectory under the cache directory. Keep repository clones and work files ephemeral initially.

**Rationale**: [Renovate's cache options](https://docs.renovatebot.com/self-hosted-configuration/) distinguish package lookups, repository extraction cache, and downloaded-tool cache. A persistent cache directory serves the request without a new Redis service. Default TTLs revalidate old data while permitting safe stale responses during upstream failures. Private package metadata on the PVC requires the existing workload namespace and storage access boundary. The cache is rebuildable, so backups are unnecessary.

**Alternatives considered**: Ephemeral storage loses cache each run. Redis adds a service and credentials for one runner. Persisting all cloned repositories consumes more disk without directly improving version lookup reuse. Custom TTL overrides risk hiding releases and are experimental.

## Decision 4 — Mint a short-lived App token from mounted files

**Decision**: Mount the existing App private key from an ExternalSecret sourced from declared SSM parameters. A small file-backed global config mints a fresh installation token at process start using Node's built-in crypto and GitHub's App API, then gives it to Renovate in memory. Store no token on the PVC, in the pod environment, or in command arguments. Bound a run to less than the one-hour token lifetime.

**Rationale**: The [GitHub App token contract](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app) gives a one-hour token. Renovate [accepts asynchronous global config files](https://docs.renovatebot.com/config-overview/) and an installation token in its token setting. The repo already has a [Node built-in signing pattern](../../clusters/homelab/apps/openclaw/assistant/gh) and a [file-backed ExternalSecret pattern](../../clusters/homelab/apps/policy-bot/externalsecret.yaml).

**Alternatives considered**: A permanent PAT broad enough for future repositories increases exposure and changes bot identity. Passing a token by environment or CLI conflicts with repository secret conventions. A separate token service or dependency is unnecessary.

## Decision 5 — Transfer the existing key through a declared CI path

**Decision**: Add placeholder App issuer-ID/private-key parameters under /homelab/renovate in the SSM catalog, then a reviewed, one-shot protected workflow in Stuhlmuller/renovate that reads its existing GitHub Actions secrets and writes only those exact parameters through a narrowly scoped AWS OIDC role. The existing workflow supplies the value named RENOVATE_APP_ID to a client-id input, so verify its actual issuer type without exposing the value. Add the role/trust in homelab IaC first; remove temporary write access after verified ExternalSecret readiness. Never print, download, or commit the key.

**Rationale**: GitHub Actions secrets cannot be read back through the API. The current workflow already consumes the key, and homelab has [fixed-target credential workflows](../../.github/workflows/cordium-runner-credentials.yml) and [SSM/ExternalSecret contracts](../../docs/secrets-aws-ssm.md). This preserves the existing App and keeps the transfer represented in reviewed code.

**Alternatives considered**: Manual AWS/GitHub console changes violate repository rules. A new App requires a broader identity migration. Copying a secret through logs or artifacts is unsafe.

## Decision 6 — Cut over after parity evidence

**Decision**: Deploy the hourly cluster CronJob initially suspended with Renovate full dry-run mode in committed config. Verify Secret projection before unsuspending it through GitOps, then verify discovery, planned proposals, existing PR continuity, App identity, merge policy, and cache reuse. After the last legacy run finishes, delete the entire write-capable Stuhlmuller/renovate workflow in a reviewed companion PR and verify that neither its schedule nor workflow_dispatch nor any nonterminal run across scheduled and manual events remains. Retire the repository Actions private key with a guarded current-main receipt proving transferred SSM credentials, later Ready Secret projection, key absence, and drained old runs. Only then remove dry-run mode via GitOps and inspect a real scheduled run, PR authorship, repository coverage, and merge policy. If deletion, drainage, or key retirement cannot complete, stay in dry-run mode. Rollback suspends cluster writes through GitOps, verifies no pending or active Job or Pod, restores the Actions key from SSM with a guarded receipt, then restores the legacy workflow through a reviewed PR. Remove the temporary credential-transfer grant after Secret projection; a later rotation reintroduces a reviewed temporary grant.

**Rationale**: The legacy runner is owned by a different repository, so homelab alone cannot complete cutover. The homelab's [GitOps path](../../docs/argocd-app-onboarding.md) owns cluster desired state. Renovate's [full dry-run mode](https://docs.renovatebot.com/self-hosted-configuration/#dryrun) reports planned changes without writes. Existing [Job failure alerts](../../clusters/homelab/apps/prometheus/job-prometheusrules.yaml) need a separate freshness signal for missed hourly runs.

**Alternatives considered**: Disabling the old workflow before a successful full dry run creates an unverified gap. Enabling cluster writes before deleting the old workflow leaves workflow_dispatch as a second writer. Manual kubectl or GitHub UI edits bypass declared code paths.

## Decision 7 — Measure freshness with independent evidence

**Decision**: For seven-day latency, pre-register a reproducible sample spanning each active datasource class and public/private sources where present. A separate read-only observer with no shared cache brackets the first healthy upstream visibility of each sampled release; compare the conservative last-absent bound with GitHub PR or timestamped policy-deferral evidence. Keep a reviewed GitHub Release canary outside the sample to force a known refresh event. For cache reuse, require the same datasource key across distinct scheduled Pods and scoped TRACE cache-hit evidence or an independent request counter. For owner changes, test a mocked add/remove discovery sequence and verify live owner/App inventory parity plus all-repositories installation selection; record the first real transition as a later operational check.

**Rationale**: Renovate's own logs cannot count releases it never observed, and a quiet warm run is not proof of a cache hit. [Renovate's self-hosted cache and dry-run options](https://docs.renovatebot.com/self-hosted-configuration/) allow separate read-only observation and normal TTL refresh. The [GitHub Releases datasource](https://docs.renovatebot.com/modules/datasource/github-releases/) has a release timestamp suitable for a controlled event. GitHub's [installed App access settings](https://docs.github.com/en/apps/using-github-apps/reviewing-and-modifying-installed-github-apps) distinguish all-repository coverage from selected repositories.

**Alternatives considered**: Counting only Renovate-observed releases would miss false negatives. Claiming fleet-wide latency from one canary would overstate evidence. Creating or transferring a disposable owner repository needs a new privileged, repo-owned lifecycle path; a mocked transition plus live access parity provides a deterministic pre-cutover gate without that extra privilege.
