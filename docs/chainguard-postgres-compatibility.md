# Chainguard PostgreSQL compatibility prerequisite

The pinned public Chainguard candidate needs tested runtime and data contracts
before it can replace the maintained PostgreSQL images. Run
`python3 -I scripts/ci/chainguard-postgres-check.py` on a Linux Docker host.
The dedicated CI job uses pinned public source bytes without production
credentials; production replacements must use the verified Harbor copy.

The fixture and both publication catalogs use the PostgreSQL index verified
on 2026-10-11. Earlier native results do not cover this refreshed digest;
require the dedicated Linux job to pass before accepting it.

Wolfi PostgreSQL clients default to `/tmp` sockets; Debian clients default to
`/var/run/postgresql`. The fixture exposes both and waits for the final
PostgreSQL process, not the entrypoint's temporary initialization server.
Production socket/probe contracts need the same explicit review.

The fixture starts PostgreSQL 14 and 18 sources with their existing 65534/999
UID contracts, file-backed user/database/password inputs, a read-only image
and no network. The pinned Chainguard image rejects UID 999 because that account
is absent; a negative check preserves this incompatibility. Both logical
migrations restore into fresh UID 65534 tmpfs data directories. Production
migration must use a new, correctly owned data directory and verified restore;
this does not validate retaining UID 999 or changing existing volume ownership.
It exports synthetic JSONB data and global roles, checking restored roles,
Unicode, permissions, sequence and subsequent write. Containers and tmpfs data are disposable; no
production mounts, credentials, cluster access or databases are involved.

A passing fixture does not authorize an in-place major-version upgrade or
prove application compatibility, extensions, collation, real backup restore,
NFS ownership, cold recovery or Harbor self-hosting. Keep existing data volumes
and rollback images. A failed identity or entrypoint test blocks substitution
until the repository-owned workload contract is adapted and retested. No
consuming reference or production configuration changes in this prerequisite.
