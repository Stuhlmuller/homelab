# Image Automation

Renovate is the repository's image-update path. Its built-in Helm values,
Kustomize, and Kubernetes managers open reviewed pull requests for image tags
and digests. `scripts/ci/static-checks.sh` rejects every repo-declared
container image that is not pinned as `tag@sha256:digest`.

Compatibility and stateful migration decisions happen during normal pull-request
review.
