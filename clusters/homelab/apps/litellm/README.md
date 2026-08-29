# LiteLLM

LiteLLM provides the OpenAI-compatible model gateway used by OpenClaw. Human
access remains behind Octelium; workload access is limited by the `ai`
namespace Istio policies.

## Version contract

- Helm chart: `litellm-helm` `0.1.832`.
- Runtime: `ghcr.io/berriai/litellm-database:v1.96.2` pinned to the signed
  multi-platform index digest in `values.yaml`.
- `v1.96.2` is the minimum accepted runtime. It fixes the authenticated
  provider-credential exfiltration and SSRF advisory tracked in issue `#789`
  and is above the other maintainer security floors affecting the old image.

LiteLLM dropped the legacy `-stable` tag suffix in `v1.84.0`; do not restore
that suffix on newer pins. The current deployment has no database connection or
standalone database configured, and its migration Job is disabled, so this
image-only upgrade has no schema migration.

## Runtime hardening

The chart creates the dedicated `litellm` ServiceAccount with API-token
automount disabled. The Pod uses `RuntimeDefault` seccomp, prohibits privilege
escalation, and drops every Linux capability.

Phase 1 intentionally retains the image's default root user and writable root
filesystem. Add UID/GID `65534`, `runAsNonRoot`, and a read-only root filesystem
only after this phase remains healthy for 24 hours. Enabling a database or the
migration Job requires renewed writable-path testing before applying those
Phase 2 controls to the migration path.

## Rollout checks

Before merge, render the exact chart and overlay:

```sh
helm template litellm oci://ghcr.io/berriai/litellm-helm \
  --version 0.1.832 -f clusters/homelab/apps/litellm/values.yaml
kubectl kustomize clusters/homelab/apps/litellm
```

After Argo CD reports `litellm` `Synced/Healthy`, confirm the Deployment and
running Pod image IDs use the committed digest, the Pod has no service-account
token mount, `/health/readiness` succeeds, and one OpenClaw model request
completes. Observe restarts and latency for 24 hours before starting Phase 2 or
closing `#789`.

Do not roll back below `v1.96.2`. If this release fails, roll forward through
GitOps to a later signed, digest-pinned LiteLLM release.
