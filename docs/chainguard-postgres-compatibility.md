# Chainguard PostgreSQL compatibility prerequisite

The pinned public Chainguard candidate needs tested runtime and data contracts
before it can replace the maintained PostgreSQL images. Run
`python3 -I scripts/ci/chainguard-postgres-check.py` on a Linux Docker host.
The dedicated CI job uses pinned public source bytes without production
credentials; production replacements must use the verified Harbor copy.

The fixture starts PostgreSQL 14 and 18 with the existing 65534/999 UID
contracts, file-backed user/database/password inputs, a read-only image and no
network. It logically exports synthetic JSONB data and restores it into the
Chainguard candidate, checking a retained role, Unicode value, permissions,
sequence and subsequent write. Containers and tmpfs data are disposable; no
production mounts, credentials, cluster access or databases are involved.

A passing fixture does not authorize an in-place major-version upgrade or
prove application compatibility, extensions, collation, real backup restore,
NFS ownership, cold recovery or Harbor self-hosting. Keep existing data volumes
and rollback images. A failed identity or entrypoint test blocks substitution
until the repository-owned workload contract is adapted and retested. No
consuming reference or production configuration changes in this prerequisite.
