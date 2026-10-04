# Multica

Multica runs in the shared `ai` namespace with its upstream OCI Helm chart,
frontend/backend services, and dedicated pgvector PostgreSQL instance. Human
access is through Octelium at `https://multica.stinkyboi.com`.

## Server agent runtime

`runtime.yaml` runs a one-replica Multica daemon on `acer`. `Recreate`
prevents concurrent daemons against the retained `multica-runtime-local` PVC,
which stores the daemon identity, token, repositories and workspaces.

The init container installs checksum-verified Multica and OpenCode binaries.
OpenCode is configured with the internal LiteLLM endpoint and the dedicated
`multica-litellm` Secret. It may request only `openrouter/free`; the
LiteLLM gateway holds the upstream OpenRouter credential and records trusted
Multica attribution in Langfuse. No ChatGPT/Codex OAuth runtime or credential is
installed in this workload.

On first boot, `runtime/bootstrap.py` signs in with the fixed-code key from
`multica-backend-secrets`, creates a renewable 90-day personal token, and
reuses it on later boots. The daemon has no database credentials, Kubernetes
token, host sockets, or other application's home directory.

After Argo sync:

```sh
kubectl -n ai rollout status deployment/multica-runtime --timeout=10m
kubectl -n ai exec deployment/multica-runtime -- \
  /tools/multica daemon status --output json
```

Then run one bounded task using `litellm/openrouter/free` and require a
correlated Langfuse generation with input/output and nonzero usage. Daemon
health alone does not prove model authentication.

## Sign-in and storage

Secret material reaches `multica-secrets` and `multica-backend-secrets`
through External Secrets from AWS SSM. The generated bootstrap contracts are:

- `/homelab/multica/jwt-secret`
- `/homelab/multica/postgres-password`
- `/homelab/multica/dev-verification-code`

The fixed code is a trusted-operator development login and must remain behind
Octelium. Do not publish it. To roll back the runtime, set its replica count to
zero through GitOps and preserve its PVC; the web app and database are
independent.
