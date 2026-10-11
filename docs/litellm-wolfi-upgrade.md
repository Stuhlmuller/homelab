# LiteLLM Wolfi upgrade candidate

The image catalog pins the original upstream `litellm-database:main-stable`
index by digest; the workload consumes its Harbor mirror. The candidate image's
Linux configuration identifies Wolfi and source revision
`fc3920bf403124ad075bc04990f999f7e0612e12`, whose
[package metadata](https://github.com/BerriAI/litellm/blob/fc3920bf403124ad075bc04990f999f7e0612e12/pyproject.toml)
declares LiteLLM 1.104.2. This remains an upstream application image built on
Wolfi; it is retained as an exception to a direct public Chainguard application
image. Do not rewrite index bytes or weaken Harbor database constraints.

The gateway keeps one guarded Uvicorn worker, file-backed credentials, native
key authentication and OpenRouter-only inference. Its Langfuse logger always
uses the operator-configured tracer. This prevents the upgraded SDK's dynamic
tracer construction from changing the collector endpoint or credentials.

Native checks now use the reviewed SDK and Starlette versions, IdentityStore's
database lookup seam, real proxy/logging objects, and the packaged Prisma
schema. They require revocation and route/model limits, rejection of the former
Host bypass, early credential redaction, one deduplicated failure span, safe
streaming telemetry and unchanged exception identity. Disposable PostgreSQL
checks cover atomic key import, concurrency, UI rotation/revocation, encrypted
provider storage and fail-closed reads. A separate database applies the previous
0.4.11 package's migrations, seeds key identity/restrictions/blocking and Unicode
metadata, then applies candidate migrations and reads that state with the new
client. The previous wheel is checksum-pinned before any SQL is used. These
packages change some historical SQL and migration paths; the rehearsal requires
the previous migration ledger/checksums to remain intact. Do not resolve or
rewrite migration history to hide a failure. These checks use fixture data only;
they do not prove a production-data migration or
backup restoration.

Both Linux platforms' package metadata is inspected without extracting or
executing files; each manifest, configuration and compressed layer must match
its original digest and size. CI's SDK versions match those packaged versions.
CI also runs native authentication and telemetry checks inside the exact catalog
image with network disabled, a read-only filesystem, non-root UID and no
capabilities. The public source is used only in this disposable CI fixture;
the application reference remains Harbor. Local Docker is unavailable, so the
native Linux image job must pass before runtime compatibility is established.

`builds/litellm/Dockerfile` stages a derived runtime with explicit package
versions from the base image's existing signed package repository. Its default
base is the verified Harbor mirror; the disposable CI build substitutes the
same catalog-pinned public source, builds locally and runs the native fixtures
with network disabled. No package repository, signature requirement or SDK
version is changed. The derived image defaults to UID 65532; its declared GitOps
gateway command, actual database startup and migration behavior must also pass
before rollout. The upstream entrypoint is not the GitOps launcher.

The Linux fixture also connects the derived image to a separate disposable
PostgreSQL database through a read-only Unix-socket bind mount. Networking stays
disabled. The database accepts no TCP connections; its private parent directory
stays owner-only. UID 65532 must apply the image's packaged migrations with its
bundled offline Prisma CLI, execute the packaged query engine and pass native
key/provider persistence checks. This verifies the packaged database path rather
than only a host-installed SDK; real GitOps startup and production-data restore
remain separate gates.

The current workload reference is the imported build-source image, not a
published derived runtime. Keep this PR draft: before merging any consumer
change, replace that reference with the fully published, privately scanned and
verified Harbor digest of the derived image. Passing build/runtime fixtures does
not authorize deployment of the unremediated build source or prove zero CVEs.

CI saves the exact derived image and scans it with the repository-pinned Grype
package. The complete unsuppressed report remains private in runner temporary
storage; no report or inventory artifact is uploaded. The gate checks image
identity by hashing the scanner's complete configuration bytes against the
expected Docker image ID and requiring Linux/amd64 in that configuration.
Docker archives leave the scanner's summary platform fields empty; populated
summary fields must agree with the hashed configuration. The gate also checks
scanner version, valid recent database/report timestamps and absence
of filtering before rejecting fixable findings. Unknown or upstream-unfixed
findings remain in the private report and require separate review; passing this
gate does not establish zero vulnerabilities or authorize release. Public output
contains only fixed pass/fail messages and whitelisted validation categories
(identity, scanner, database, freshness, filtering, schema or remediation).
Malformed report values and tracebacks are never printed. Fresh Harbor scans of the published
digest remain required.

Keep the PR draft until the original all-platform image is completely pulled
from Harbor and scanned privately. Before deployment, verify its actual runtime
behavior and perform the declared database backup, restore and
schema-migration rehearsal against a private production-data copy. Fresh-schema
fixtures do not prove an upgrade of existing data. Deploy only through the
protected GitOps path after shared image/node recovery holds are released.

Acceptance includes the original application requests through the real gateway,
operator login and native key management, non-streaming/streaming completion,
revocation, caller override denial and correctly attributed Langfuse traces.
Retain the old image and a tested pre-migration database backup. If migrations
are incompatible with the old binary, rollback requires restoring that backup;
changing only the image tag is insufficient. Keep all live scan and migration
evidence outside this public repository.
