# Data Model: Renovate Runner

Renovate and GitHub own the runtime records. The homelab declares scheduling, policy, secret references, and cache storage; it adds no application database.

## Repository

| Field | Meaning |
| --- | --- |
| owner/name | Stable GitHub repository identity; owner must be Stuhlmuller. |
| visibility | Public or private; never printed in public diagnostic output for private repositories. |
| archived/fork/access | Determines whether the App can scan and propose updates. Owned forks are included; archived repositories are skipped, and missing App access to a non-archived owned repository blocks cutover. |
| config source | Committed global policy plus repository Renovate settings when present, using Renovate's normal precedence. |
| last outcome | Success, explicit deferral, skip, or failure in the most recent discovery cycle. |

**Rules**: Each cycle rediscovers repositories accessible to the App and filters to the owner. A repository is scanned at most once per cycle. Removal from the owner stops future scans; it does not delete GitHub PRs or the cache manually.

## Discovery Cycle

| Field | Meaning |
| --- | --- |
| scheduled/start/end time | Evidence for hourly start latency and duration. |
| Job identity | Unique Kubernetes Job/Pod created by the CronJob. |
| repository outcomes | One sanitized result per eligible repository. |
| state | Scheduled → Running → Succeeded or Failed; a missed schedule is observable separately. |

**Rules**: No cycle overlaps another. A Job must finish before its App token expires. Failure keeps retained Job evidence and permits the next hourly cycle to retry.

## Version Cache

| Field | Meaning |
| --- | --- |
| cache key and scope | Renovate-owned datasource/package or repository-extraction identity. |
| value | Release metadata, digest lookup, extraction result, or downloaded tool. May contain private package metadata. |
| freshness | Renovate-owned soft refresh and hard expiry. |
| storage | One protected, retained PVC mounted at the cache directory. |

**Rules**: Valid entries survive Job and pod replacement. Expired entries are revalidated. Missing or corrupt entries are rebuilt. No token or private key is written to this PVC; it is operational cache, not a backup source.

## Runner Credential

| Field | Meaning |
| --- | --- |
| App identity | Existing Renovate GitHub App JWT issuer ID and installation for Stuhlmuller. |
| private key | SSM SecureString materialized as a read-only mounted file. |
| installation token | Minted in memory at Job start, scoped to the owner's installation, expires after one hour. |

**Rules**: The transfer CI role can write only the declared App parameters. The workload reads only the mounted key. Credential rotation is verified by a new scheduled Job, without printing values.

## Update Proposal

| Field | Meaning |
| --- | --- |
| repository/branch/PR | GitHub-owned identity for an update. Existing PRs remain attached to the same App author. |
| effective policy | Global policy merged with repository config, where present. |
| state | Proposed → Checks/review → Auto-merged when policy and branch protection allow, or remains open/closed. |

**Rules**: Renovate never writes directly to a protected default branch. The existing daily auto-merge policy remains; repository checks, approvals, and merge restrictions decide whether merging can occur.

## Acceptance Observation

| Field | Meaning |
| --- | --- |
| sample key | Pre-registered repository, datasource, and package, selected with a reproducible seed across used datasource classes; observed versions are appended when detected. |
| visibility bracket | Last healthy independent upstream poll without the release and first healthy poll with it. |
| outcome time | GitHub PR creation/update or timestamped policy deferral, with reason. |
| classification | Eligible, excluded outage/policy case, timing-ambiguous, or controlled canary. |

**Rules**: The observer uses no production Renovate cache and makes no GitHub writes. A private ledger stays outside git; only aggregate counts and safe examples are published. The controlled canary is separate from the 95% sampled denominator. Fewer than ten eligible independent observations makes the seven-day latency result inconclusive.
