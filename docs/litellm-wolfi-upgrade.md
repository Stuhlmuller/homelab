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
provider storage and fail-closed reads. These checks use fixture data only.

Keep the PR draft until the original all-platform image is completely pulled
from Harbor and scanned privately. Before deployment, verify its installed
package/runtime contents and perform the declared database backup, restore and
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
