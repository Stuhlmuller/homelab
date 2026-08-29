# Issue 789 Security Patch Baseline

Tags: #operations #security #workloads #stateful

Source: [GitHub issue #789](https://github.com/Stuhlmuller/homelab/issues/789)

Research date: 2026-08-29

Status: phase 1 desired state is prepared only. It updates Octelium storage and
must remain unmerged until its live preflight blockers pass. Every other row
below is research for a later, independent branch; no later-phase manifest is
changed here.

## Phases

| Phase | Scope | Previous | Researched target | Implementation |
| --- | --- | --- | --- | --- |
| 1 | Octelium PostgreSQL | `14.23-bookworm` | `14.24-bookworm` | Prepared in this branch |
| 1 | Octelium Redis | `7.4.2-alpine` | `7.4.11-alpine` | Prepared in this branch |
| Later | media PostgreSQL | `14.23-bookworm` | `14.24-bookworm` | Unimplemented |
| Later | n8n PostgreSQL | `14.23-bookworm` | `14.24-bookworm` | Unimplemented |
| Later | n8n app and wait client | n8n `2.30.6`; client `18.4` | n8n `2.36.8`; client `14.24` | Unimplemented |
| Later | Dispatcharr PostgreSQL | `17.5-bookworm` | `17.11-bookworm` | Unimplemented |
| Later | AFFiNE Redis | `8.2.1-bookworm` | `8.2.9-bookworm` | Unimplemented |
| Later | LiteLLM | `1.80.8` | `1.96.2` | Unimplemented |

Each later scope needs a fresh branch from then-current `main`, revalidated
release and registry evidence, its own backup/preflight gate, rollout, smoke
test, and 24-hour observation. Do not stack or merge these phases together:
all affected Argo CD Applications auto-sync `main` independently.

PostgreSQL 14 remains supported only until 2026-11-12. Its major migration is
a separate backed-up change and must not be folded into a minor security patch.

## Phase 1 Compatibility

- PostgreSQL 14.24 is an in-place minor update. The upstream release notes say
  no dump/restore is required, but call out logical output plugins, `pgcrypto`,
  and possible `btree_gist`/`ltree` reindex work. Repository source declares
  none of these; only the live catalog can rule out runtime-created objects.
- Redis stays on the supported 7.4 line and retains Alpine, UID/GID, command,
  port, probes, AOF configuration, and PVC contract. Its AOF is control-plane
  state, so a proven backup/recovery decision is still mandatory.
- The Octelium Application applies PostgreSQL at Argo CD sync wave 0, updates
  the backup CronJob at wave 1, and applies Redis at wave 2. Argo CD waits for
  the earlier wave to become healthy before continuing. A PostgreSQL failure
  therefore prevents the Redis restart.

## Phase 1 Primary Sources

- PostgreSQL's [versioning policy](https://www.postgresql.org/support/versioning/)
  lists 14.24 as current and PostgreSQL 14 end-of-life as 2026-11-12.
- PostgreSQL's
  [14.24 release notes](https://www.postgresql.org/docs/14/release-14-24.html)
  define the in-place update and catalog/reindex caveats.
- Redis's [security policy](https://github.com/redis/redis/security/policy)
  marks 7.4 supported. The official
  [7.4.11 release](https://github.com/redis/redis/releases/tag/7.4.11) is the
  latest same-line security patch on the research date.
- Argo CD's
  [sync phase and wave documentation](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/)
  defines ordered wave application and health gating.

## Phase 1 Immutable Image Evidence

The Docker Hub OCI Distribution endpoint was queried directly with the OCI
index media type on 2026-08-29. Both tags returned HTTP 200 and these
`Docker-Content-Digest` values. Linux amd64 and arm64 platform manifests were
also present; the OCI index preserves portability, but current arm64 scheduling
is unverified.

| Image tag | OCI index digest | linux/amd64 | linux/arm64 |
| --- | --- | --- | --- |
| `redis:7.4.11-alpine` | `sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf` | `sha256:1db42ccef14898aa29bae778452d567534b59c107129cbc1163fb552de184d3c` | `sha256:f8d15882ba108587477ce13c00ab0551933a84138427b7cc9abadfbe45ffd973` |
| `postgres:14.24-bookworm` | `sha256:185c7c7a36448bcb7e0d3d6aef97ac973ddfae0cc4fa29581ce4e789988a74b1` | `sha256:1e2dc0602e97c39e6af814b227cc83ff109aabc793f42ae61f7fa148f15a62a4` | `sha256:af520401f22f4b76a7df1b5998dd78cd9320ae6d56786b35077bdf79e193ce79` |

Static checks assert the semantic tag, OCI index digest, occurrence count,
absence of the two superseded Octelium pins, and the `0`/`1`/`2` sync waves.

## Phase 1 Pre-Merge Gate

Read-only Kubernetes access timed out at `https://10.1.0.199:6443` on the
research date. Do not merge until all evidence below is attached to the review:

1. The latest `octelium-postgres-backup` Job is successful and less than 24
   hours old. Its log must contain `completed backup`; reaching that line proves
   `pg_restore --list` and both checksum passes succeeded.
2. Query `pg_replication_slots` for non-built-in output plugins. Inventory every
   connectable, non-template database and query each database's `pg_extension`
   for `pgcrypto`, `btree_gist`, and `ltree`. Empty plugin and per-database
   extension results satisfy the release-note preflight. Any result needs a
   reviewed configuration, data-cleanup, or reindex plan before merge.
3. Complete the documented PostgreSQL restore drill tracked by
   [issue #790](https://github.com/Stuhlmuller/homelab/issues/790). The current
   archive-list check proves structure, not an application-ready restore.
4. Provide a repository-owned Redis AOF backup/restore path, or prove from
   Octelium's owned contract that this Redis state is safely rebuildable. The
   current repository has neither, so Redis recovery remains a blocker.
5. Record current PostgreSQL and Redis pod restart counts, PostgreSQL `SELECT
   1`, Redis authenticated `PING`, Redis persistence status, and Octelium
   portal/API/service health as the before-state.

Useful read-only checks are in
`clusters/homelab/apps/octelium-storage/README.md`. No manual Kubernetes, NAS,
or cloud mutation is an acceptable substitute for a missing repository path.

## Phase 1 Rollout And Rollback

After the pre-merge gate passes, merge only this phase. Argo CD first replaces
PostgreSQL. It must report healthy and answer SQL before Redis is applied. The
backup CronJob image is updated between them without starting an ad hoc Job.

- If PostgreSQL fails before wave 2, revert the phase commit through Git; Redis
  remains unchanged. Preserve both PVCs.
- If Redis fails after PostgreSQL is healthy, make a reviewed Git change that
  restores only the prior Redis image while leaving PostgreSQL 14.24 in place.
  Restore the pre-rollout AOF recovery point only through its declared path.
- If PostgreSQL starts and then shows data-level inconsistency, do not blindly
  downgrade binaries. Fence through repository-owned desired state and use the
  proven pre-rollout restore path.
- Never delete, patch, restart, or force-recreate either live StatefulSet or
  PVC as an ad hoc repair.

## Phase 1 Post-Rollout Gate

Before closing phase 1, require PostgreSQL `SELECT 1`, authenticated Redis
`PING`, healthy AOF status, zero unexpected restarts, and successful Octelium
portal login, API access, policy evaluation, Session creation, and Service
publication. Observe for 24 hours and review pod restarts, CPU/memory,
PostgreSQL errors and query latency, Redis persistence/errors, and Octelium
control-plane failures. Only then prepare the next independent phase.

## Later-Phase Research Only

As of the research date, Redis 8.2.9, PostgreSQL 17.11, and n8n 2.36.8 are the
current same-line/non-prerelease targets. LiteLLM advisory
[GHSA-3cv6-jpf6-8222](https://github.com/BerriAI/litellm/security/advisories/GHSA-3cv6-jpf6-8222)
names v1.96.2 as its exact fix and separately notes unspecified 1.88.x
backports. Use the exact reviewed 1.96.2 target, not 1.98.0, when the independent
LiteLLM phase starts. The original 1.83.7 issue floor remains below later
critical and high advisory floors. Reverify all facts and OCI digests at
implementation time.

The dependency dashboard's open
[PR #772](https://github.com/Stuhlmuller/homelab/pull/772) changes only the
`n8n:stable` digest and lacks the semantic tag and migration gate. Open
[PR #827](https://github.com/Stuhlmuller/homelab/pull/827) retains PostgreSQL
14.23. Keep both unmerged; later #789 phases supersede them.
