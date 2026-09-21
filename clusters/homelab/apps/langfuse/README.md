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
2. Verify the Langfuse Application is Synced/Healthy, all three PVCs are Bound,
   the project is initialized, and the authenticated UI opens through Octelium.
   Verify `langfuse-secrets`, `litellm-app-keys` and `openclaw-langfuse-otel`
   ExternalSecrets are Ready without printing their values.
3. Prepare the existing caller changes in a fresh branch:

   ```sh
   nix develop --command python3 scripts/ci/langfuse-staging-check.py
   git apply --check docs/examples/langfuse/activate-callers.patch
   git apply docs/examples/langfuse/activate-callers.patch
   ```

   The staging check applies the patch only to scratch and exercises both
   OpenClaw telemetry/config fixtures. It fails on stale patch context or an
   outdated assistant checksum. Refresh the patch after overlapping changes;
   preserve newer image, timeout and agent settings. In the activation PR,
   remove the consumed patch and staging check (including its static-gate
   invocation), then run the full static gate and pinned LiteLLM attribution
   test. Review the live plan and render/diff the affected workloads.
4. After activation, verify one real OpenClaw OAuth turn and gateway request
   produce correlated traces with expected provider/model, content and available
   usage. Keep the working ChatGPT subscription and n8n Bedrock workflow.
5. Activate NOFX separately using its
   [image and routing gates](../nofx/README.md#deferred-litellm-routing).
   Its prepared `activate-nofx.patch` does not select an image: pair it with the
   verified published backend digest containing source patch `0012` only after
   LiteLLM and `nofx-litellm` are Ready. Preserve the original provider/model and
   require a real correlated trace without credential leakage.

Rollback the activation commit through GitOps; retain Langfuse data and keys.
The staging merge does not establish inference coverage or a datastore restore
drill. Those acceptance gaps remain in the knowledge base.
