# Tines Desired State

The public repository does not commit a floating Tines image tag. The
self-hosted Tines image is expected to come from a licensed registry path, so
the chart is pinned to the placeholder `pinned-version-required` and scaled to
zero replicas until an operator replaces it with a reviewed immutable release
tag.

Before enabling runtime use:

- Replace `pinned-version-required` with the licensed, immutable Tines image tag.
- Add any required image pull secret through External Secrets.
- Confirm NFS backup coverage for automation history and runtime state.
