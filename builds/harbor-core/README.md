# Harbor core duplicate-index prerequisite

The pinned Harbor v2.15.4 manager writes every index descriptor as a database
relation. Identical repeated child descriptors violate the existing unique
parent/child constraint, blocking faithful full-catalog publication.

This candidate deduplicates only identical database relations. It retains the
original artifact digest and descriptor list and rejects differing digest,
platform, URL or annotation metadata for the same child before any DAO write.
The repair changes neither registry index bytes nor database schema.

The source archive is pinned and hash-verified before safe extraction and patch
application. The Linux amd64 recipe uses the pinned public Chainguard Go build
image and preserves the official v2.15.4 runtime payload, user and entrypoint.
API bindings use upstream's pinned Swagger v0.33.1 and committed templates.
It replaces only `/harbor/harbor_core`. All four current nodes are amd64;
other architectures require a separately tested build.

Run `bash builds/harbor-core/build.sh` on a Linux Docker host. Its native build
first requires the unpatched manager to fail the repeated-child regression,
then requires the repaired manager suite and complete core compilation to pass
with networking disabled after dependency download.

This is a build prerequisite, not a rollout or CVE-free acceptance claim.
Docker is unavailable on the current macOS operator host. Require Linux image
build, real disposable Harbor/PostgreSQL index push/pull, unchanged raw index
digests, complete private scans and protected publication before changing
consumers. Couple any v2.15.4 rollout with the matching chart/components and
verified database/blob/key backups. Keep the upstream cold-bootstrap and
rollback images; do not alter the live uniqueness constraint as a workaround.
