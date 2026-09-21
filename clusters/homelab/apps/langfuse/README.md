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

Langfuse raw events use a dedicated S3 bucket with a 30-day object-retention
policy. This is not a database backup: there is no automatic logical backup or
restore job for PostgreSQL, Valkey, or ClickHouse. Retained PVCs protect
against accidental GitOps deletion but are not an independent recovery copy.
Treat state recovery as unverified until a restore procedure and drill exist.

## Validation

```sh
kubectl kustomize clusters/homelab/apps/langfuse
scripts/octelium-e2e-check.sh
```
