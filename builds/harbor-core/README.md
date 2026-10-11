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

The dependency patch requires Go 1.27.2 and updates affected NTLM, networking,
crypto, Helm, telemetry and compression libraries to the resolved current
versions. The advisory-recommended `filippo.io/csrf/gorilla` compatibility
package replaces gorilla/csrf. It preserves the response token header while
enforcing browser origin/Fetch metadata; tokens are no longer the check, and
nonbrowser requests remain allowed. Native tests cover UI/session-origin
denials, valid same-origin requests and the existing non-session API exemption.
Harbor's declared CSRF key contract and invalid-key refusal remain intact.

A local Linux binary scan after these changes still reports four Distribution
v2 findings and one x/crypto finding as unfixed/unknown. Do not suppress these
or treat the binary-only scan as final container or deployed-digest acceptance.

The affected OpenPGP and Distribution proxy/storage/handler packages are absent
from core's compiled dependency graph; the build guards against introducing
them. A native positive/negative JWK test also verifies that the v2 token parser
uses actual key material and rejects an attacker key with a forged trusted key
ID. Record these specific advisory assessments alongside unfiltered reports;
they do not clear other Harbor components or the final container.

After the Linux image/registry fixture, CI saves the exact built container and
runs lock-pinned Grype 0.112.0 with a fresh advisory database. The audit checks
the image/config hash, Linux amd64 platform, Photon 5.0 identification, report
freshness and absence of exclusions/VEX/filtering. Available fixes fail the
audit. Unfixed/unknown matches remain counted and are not CVE clearance or
publication approval. Raw image metadata and transport output stay private;
temporary scan inputs are removed on exit.

Run `bash builds/harbor-core/build.sh` on a Linux Docker host. Its native build
first requires the unpatched manager to fail the repeated-child regression,
then requires the repaired manager suite and complete core compilation to pass
with networking disabled after dependency download.

The same command then prepares an isolated upstream Harbor stack with pinned
v2.15.4 component images and the candidate core. Its service network denies
external access and publishes no host ports. The test client shares the proxy's
network namespace and uses `127.0.0.1:8080`. A tiny OCI
image with eight identical child descriptors must push and pull unchanged,
including every blob, while PostgreSQL stores exactly one child relation.
The fixture owns temporary credentials/data and removes its containers,
network and files on exit. No cluster or production registry credentials apply.

This is a build prerequisite, not a rollout or CVE-free acceptance claim.
Docker is unavailable on the current macOS operator host. Require the Linux
build and registry fixture to pass, complete private scans and protected publication before changing
consumers. Couple any v2.15.4 rollout with the matching chart/components and
verified database/blob/key backups. Keep the upstream cold-bootstrap and
rollback images; do not alter the live uniqueness constraint as a workaround.
