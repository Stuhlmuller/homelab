# Tines Desired State

The public repository does not commit a floating Tines image tag. The
self-hosted Tines image is expected to come from a licensed registry path, so
the chart is pinned to the placeholder `pinned-version-required` and scaled to
zero replicas until an operator replaces it with a reviewed immutable release
tag.

Before enabling runtime use:

- Replace `ghcr.io/tines/self-hosted:pinned-version-required` with the
  licensed registry path and immutable Tines image tag, or with a reviewed
  private mirror path.
- Update `/homelab/tines/registry-dockerconfigjson` in AWS SSM Parameter Store
  with the full Docker `config.json` for the registry or mirror. This keeps the
  pull secret registry-agnostic instead of assuming GitHub Container Registry
  username/password fields.
- Confirm NFS backup coverage for automation history and runtime state.
