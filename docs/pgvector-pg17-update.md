# PostgreSQL 17 pgvector update

HOME-49 reconciles [Renovate PR #1143](https://github.com/Stuhlmuller/homelab/pull/1143)
with the reviewed Harbor catalog. This is a desired-state change; no live
database, backup, restore, publication or rollout result is asserted here.

## Immutable identities and compatibility

Repository: `docker.io/pgvector/pgvector`.

| Role | OCI index digest |
| --- | --- |
| Prior declared / rollback | `sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f` |
| Candidate | `sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d` |

Anonymous Docker Registry API reads on 2026-10-04 verified SHA-256 over the
exact bytes of both indexes, all their Linux platform manifests, and configs.
Both indexes contain Linux amd64 and arm64 images. Both platform configs on
both versions declare `PG_MAJOR=17`, `PG_VERSION=17.11-1.pgdg12+2`,
`PGDATA=/var/lib/postgresql/data`, entrypoint `docker-entrypoint.sh`, command
`postgres`, and `LANG=en_US.utf8`. Build history uses Bookworm packages and
pgvector v0.8.6 for the prior image, v0.8.7 for the candidate.

| Candidate platform | Manifest digest |
| --- | --- |
| linux/amd64 | `sha256:cd4ccfdaf62cbfeb5c6ee19ef0dd663406d4ed740c320b324d016a90e85385b3` |
| linux/arm64 | `sha256:215ae4d47393a980e9ef7ff7760f7dad53ec3e84bceb9fbd45cef34e50b5ba0f` |

The [v0.8.7 changelog](https://github.com/pgvector/pgvector/blob/v0.8.7/CHANGELOG.md)
reports IVFFlat index-build buffer-overflow and empty-average fixes.
The [extension update script](https://github.com/pgvector/pgvector/blob/v0.8.7/sql/vector--0.8.6--0.8.7.sql)
exists, but changing an image does not execute it. Registry metadata is not
proof of installed binary behavior or the extension version in an existing
database. No PostgreSQL major migration or automatic extension migration is
part of this change.

## Publication before consumers

1. Review and merge only the prerequisite catalog/docs change through existing
   signed-commit, independent platform/security review and static CI gates.
   The catalog adds the candidate as a digest-only source, retains the old
   index and its sole `pg17` alias, and leaves the PG16/AFFiNE entries unchanged.
   Digest-pinned consumers do not require promotion of the mutable alias.
2. Obtain separate authorization for publication. Follow
   [Harbor image mirroring](harbor-image-mirroring.md): dispatch the protected
   workflow for exact reviewed `main`, preserve every platform digest, verify
   complete anonymous downloads and review scanning results. Record the run
   and publication bundle revision. A passing coverage check proves none of
   these operations. Retain existing signing requirements; public mirror
   coverage does not assert private-image signature verification.
3. Keep #1143 unmerged until publication and database acceptance gates pass.
   Incorporate the companion values correction into its existing branch;
   rebase onto the published catalog revision and rerun current-head CI/review.
   Check all three declarations resolve to the candidate:
   `clusters/homelab/apps/langfuse/datastores.yaml`,
   `clusters/homelab/apps/multica/postgres.yaml`, and
   `clusters/homelab/apps/multica/values.yaml` (`images.postgres.tag`).
   Multica sets `postgres.external.enabled: true`; its chart image setting is
   inactive today, but must not retain a divergent default. Preserve that flag.
4. Before an authorized consumer merge/rollout, privately inventory
   `SHOW server_version`, `SHOW data_directory`, and
   `SELECT extname, extversion FROM pg_extension WHERE extname = 'vector'`
   for both databases. Require major 17, expected data paths, and an explicit
   extension-version decision. Stop if live state differs from expectations.
   Require verified pre-upgrade logical dumps, coordinated retained-volume
   recovery points, and restore evidence per [storage recovery](storage-nfs.md).
   Multica's database and uploads need the same recovery point; Langfuse's
   PostgreSQL, ClickHouse and object-store recovery must be coordinated.
5. In a separately authorized disposable synthetic fixture, test startup with
   existing major-17 data, vector queries/indexes, application migrations,
   backup/restore, and rollback. Any `ALTER EXTENSION` or application schema
   migration needs its own reviewed procedure; do not run it as an implicit
   image-update step. No real data or live mutation is authorized by HOME-49.
6. After separately authorized GitOps rollout, require both PostgreSQL
   deployments healthy, expected image IDs and SQL readiness, plus Langfuse
   ingestion/query and Multica login/task/upload acceptance. Retain the two
   consecutive successful scheduled observations before issue closure.

## Validation and rollback

From each exact reviewed revision, run:

```sh
python3 -I scripts/ci/harbor-images-check-test.py
python3 -I scripts/ci/harbor-images-check.py
kubectl kustomize clusters/homelab/apps/langfuse >/dev/null
kubectl kustomize clusters/homelab/apps/multica >/dev/null
git diff --check
```

Also require the full current-head static CI gate. A combined local integration
checkout is useful evidence, but cannot substitute for checks on the final
rebased consumer PR. Catalog, consumer and CI revisions must be recorded.

Before consumer rollout, rollback is simply deferral; retain the additional
catalog artifact. After rollout, prepare a reviewed GitOps revert of all three
consumer declarations to the full prior digest above, preserve credentials,
PVCs, `PGDATA`, UID/GID 65534, probes and `Recreate` strategy, and verify the
retained old artifact is completely pullable before approving that action.
Do not delete the candidate or old catalog entries or change mirror fallback.

Image rollback alone is acceptable only after verifying database/extension and
application schema compatibility with the old binaries. If extension or schema
migrations occurred, stop and use the separately reviewed restore procedure
and coordinated pre-upgrade recovery point; do not assume an extension
downgrade or overwrite existing PVCs. Revalidate SQL and application behavior
after any authorized rollback. No merge, publication, deployment or rollback
execution is authorized by this document.
