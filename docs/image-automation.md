# Image Automation

Renovate is the repository's image-update path. Its built-in Helm values,
Kustomize, and Kubernetes managers open reviewed pull requests for image tags
and digests. `scripts/ci/static-checks.sh` rejects every repo-declared
container image that is not pinned as `tag@sha256:digest`.

OctoBot remains limited to `2.1.1` in `renovate.json` because `2.1.13` rejects
the retained PVC-backed `config.trading.paused` value. Other compatibility and
stateful migration decisions happen during normal pull-request review.
