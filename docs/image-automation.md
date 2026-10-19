# Image Automation

Renovate is the repository's image-update path. Its built-in Helm values,
Kustomize, and Kubernetes managers open reviewed pull requests for image tags
and digests. `scripts/ci/static-checks.sh` rejects every repo-declared
container image that is not pinned as `tag@sha256:digest`.

Compatibility and stateful migration decisions happen during normal pull-request
review.

The in-cluster runner is declared at
[`clusters/homelab/apps/renovate`](../clusters/homelab/apps/renovate/README.md)
and registered through Terragrunt. It discovers Stuhlmuller-owned repositories
hourly and retains Renovate's replaceable package cache on a protected claim.
Its first rollout is suspended and configured for full dry runs. The existing
GitHub Actions runner remains the only writer until dry-run parity, complete
legacy workflow deletion, drainage of its unfinished runs, and guarded
retirement of its repository Actions private key are verified.
