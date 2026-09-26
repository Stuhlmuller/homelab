# Langfuse

Langfuse is the homelab LLM-observability service. Its operator UI is
`https://langfuse.stinkyboi.com`, protected by the Octelium
`homelab-human-web-access` policy.

The public path is Cloudflare Tunnel -> Octelium `WEB` Service -> Istio
`VirtualService` -> `langfuse-web.langfuse.svc.cluster.local:3000`. Do not add
Tailscale Funnel or a direct Ingress.

The application owns the dedicated `langfuse` namespace and deploys the
Langfuse chart `2.1.1`. The upstream bundled datastores are disabled. The
overlay owns direct, single-replica `Recreate` Deployments for PostgreSQL
(`20Gi`), Valkey (`8Gi`), and ClickHouse (`100Gi`), each on a retained
`nfs-default` PVC. No database operator is installed.

The namespace joins Istio ambient with default-deny authorization. Only the
ingress gateway and declared AI service accounts reach the web service, and
only Langfuse's service account reaches the datastores. Datastore passwords
are mounted as files; the containers run without root and with read-only image
filesystems. ClickHouse receives writable temporary/user-config directories.

Langfuse raw events, uploaded media and batch exports share a dedicated S3
bucket with a 30-day object-retention policy (noncurrent versions expire after
7 days). Media links and export downloads therefore expire too; download any
export needed longer before that limit. This is not a database backup: there is no automatic logical backup or
restore job for PostgreSQL, Valkey, or ClickHouse. Retained PVCs protect
against accidental GitOps deletion but are not an independent recovery copy.
Treat state recovery as unverified until a restore procedure and drill exist.

## Validation

Use the protected full Terragrunt apply, not an Application-only dispatch;
it provisions SSM and S3 before Application registration. Initial login is
`operator@stinkyboi.com`, with the generated password at
`/homelab/langfuse/init-user-password` in SSM (`us-west-2`). Retrieve it only
through authenticated private secret access; never paste it into PRs or logs.
[Headless initialization](https://langfuse.com/self-hosting/administration/headless-initialization)
creates missing resources rather than resetting existing users.

```sh
kubectl kustomize clusters/homelab/apps/langfuse
kubectl -n argocd get application langfuse
kubectl -n langfuse get externalsecret,pvc,deploy
scripts/octelium-e2e-check.sh
```

## Caller activation

This change stages Langfuse and its credentials first. Existing OpenClaw and
LiteLLM runtime configuration stays unchanged: an asynchronous protected full
apply must not race a caller restart requiring credentials that do not exist.
The old OpenClaw gateway token still aliases the operator master key; the new
`/homelab/openclaw/litellm-app-token` is provisioned independently. Do not rotate
the old parameter during staging.

Before a follow-up activation PR:

1. Complete the protected full `Terragrunt Apply`, which plans/policy-checks the
   SSM/S3 producers before registering Langfuse. An Application-only dispatch
   cannot provision these dependencies.
2. Reconcile the separate Octelium catalog and public DNS paths. Terragrunt does
   not apply either. From a clean checkout of the reviewed current `main`,
   verify the exact commit before using the existing authenticated operator
   [catalog path](../../../../docs/octelium.md):

   ```sh
   (
   set -e
   git fetch origin main
   test -z "$(git status --porcelain)"
   test "$(git rev-parse HEAD)" = '<reviewed-main-sha>'
   test "$(git rev-parse origin/main)" = '<reviewed-main-sha>'
   octeliumctl apply --domain stinkyboi.com --include ClusterConfig docs/examples/octelium/homelab-services.yaml
   octeliumctl apply --domain stinkyboi.com docs/examples/octelium/homelab-services.yaml
   )
   ```

   Use authenticated operator access; never add `--prune`. Stop on any reported
   apply failure. Wait for Argo CD's `octelium-public` Application to be
   Synced/Healthy with the new tunnel pod revision before dispatching DNS:

   ```sh
   gh workflow run octelium-public-tunnel.yml --ref main -f expected_sha='<reviewed-main-sha>'
   ```

   Obtain normal `homelab-production` approval and require that exact run to
   succeed. If `main` changed, review the new commit before redispatching; do
   not bypass SHA or environment gates or edit DNS in the provider console.
3. Verify the Langfuse Application is Synced/Healthy, all three PVCs are Bound,
   the project is initialized, and the authenticated UI opens through Octelium.
   Verify `langfuse-secrets`, `litellm-app-keys` and `openclaw-langfuse-otel`
   ExternalSecrets are Ready without printing their values.
   Run `nix develop --command python3 scripts/octelium-tunnel-check.py` and
   `scripts/octelium-e2e-check.sh`; DNS/catalog/backend or login failures block
   caller activation. An unauthenticated redirect alone is not UI acceptance.
4. Prepare the existing caller changes in a fresh branch:

   ```sh
   nix develop --command python3 scripts/ci/langfuse-staging-check.py
   git apply --check docs/examples/langfuse/activate-callers.patch
   git apply docs/examples/langfuse/activate-callers.patch
   ```

   The staging check applies the patch only to scratch and exercises both
   OpenClaw telemetry/config fixtures. It fails on stale patch context or an
   outdated assistant checksum. Refresh the patch after overlapping changes;
   preserve newer image, timeout and agent settings. Its OpenClaw portion stages
   direct OTLP, not the newer free-model gateway route. Replace that portion
   with the tested gateway-only route before activation: native OpenClaw exports
   overlapping per-call and run-total usage, so enabling it alongside gateway
   capture would not provide a single token-accounting source. In the activation PR,
   remove the consumed patch and staging check (including its static-gate
   invocation), then run the full static gate and pinned LiteLLM attribution
   test. Review the live plan and render/diff the affected workloads.
5. After activation, verify one real OpenClaw free-model turn and gateway request
   produce correlated traces with expected provider/model, content and available
   usage. Preserve `openrouter/free` for interactive turns, heartbeat and
   schedules, along with the retained Astra OAuth recovery metadata. Keep the
   n8n Bedrock workflow unchanged.
6. Activate NOFX separately using its
   [image and routing gates](../nofx/README.md#deferred-litellm-routing).
   Its prepared `activate-nofx.patch` does not select an image: pair it with the
   verified published backend digest containing source patch `0012` only after
   LiteLLM and `nofx-litellm` are Ready. Preserve the original provider/model and
   require a real correlated trace without credential leakage.

Rollback the activation commit through GitOps; retain Langfuse data and keys.
The staging merge does not establish inference coverage or a datastore restore
drill. Those acceptance gaps remain in the knowledge base.
