# Validation Quickstart

Run from the repository root. Use the locked Nix development shell (`nix develop --no-update-lock-file
--no-write-lock-file`) for the commands below. Provider initialization and Helm
chart download require network access; the offline suite does not run those.

```sh
python3 -I scripts/ci/argocd-image-updater-test.py --unit
python3 -I scripts/ci/argocd-image-updater-policy-test.py
python3 -I scripts/ci/argocd-image-updater-policy.py
python3 -I scripts/ci/argocd-image-updater-provider-test.py
python3 -I scripts/ci/argocd-computed-fields-test.py
python3 -I scripts/ci/image-automation.py check
python3 -I scripts/ci/image-automation.py render-check
python3 -I scripts/ci/speckit-check.py
git diff --check
```

The provider test must use provider 3.2.1 and a controlled API fixture or a
throwaway test cluster, never mutate the live homelab for a synthetic test.
It reports the effective digest after metadata changes, selector changes,
recreation and intervening plan/apply updates for both supported source forms.
A mock that merely copies the intended provider algorithm is insufficient.
Negative cases reject empty/seeded runtime override collections and unsupported ownership mixtures, wrong path/tag/repository
policy exceptions, missing or broad Renovate exclusions, unproven image sources,
and dangerous workflow writes. The provider suite also pauses and returns to
the default module with an explicit empty/replacement override list, proving
no Application replacement or stale override survives. Separately, the temporary
paused handoff keeps runtime collections omitted, preserves the current effective
image through the source edit and reenrollment, and retains exact Renovate/policy
ownership via `image_update_handoff`. Reject active+handoff declarations and
unpaused handoffs. No synthetic test may copy a resolved digest into desired
configuration to claim the no-code-hash acceptance path. Render the pinned controller Helm chart and validate native CR schema;
run actionlint and the relevant repository static checks.

Before source delivery, inspect the exact protected PR plan: default Applications
must be unchanged and enrolled resource identities must not be replaced. Follow
the existing protected-PR and release-verification skills for delivery and apply.

After controller registration through the declared path, use read-only evidence:

```sh
kubectl -n argocd get application argocd-image-updater
kubectl -n argocd get deployment argocd-image-updater
kubectl -n argocd get imageupdaters.argocd-image-updater.argoproj.io
```

Use the existing `scripts/verify-gitops.py` against the reviewed actual revision.
Controller readiness with an empty enrollment proves readiness only, not image
updates. No workload tag was supplied for this change.

For later operator-selected enrollment, publish A then B behind that same tag
using its existing declared publisher, verify B within two successful intervals,
then run the normal plan/apply with an unrelated metadata change and verify B
survives. Change the selector, verify its current content, pause and verify no
subsequent digest change. Capture revisions and outcomes without credentials.
Keep runtime acceptance pending until that actual target test succeeds.

For a preinstalled provider, pass `--plugin-dir PATH` to the provider test.
Render and validate the pinned chart from the repository root:

```bash
nix develop --no-update-lock-file --no-write-lock-file --command bash -euo pipefail -c '
  rendered_chart=$(mktemp)
  trap "rm -f -- \"$rendered_chart\"" EXIT
  helm template argocd-image-updater argocd-image-updater \
    --repo https://argoproj.github.io/argo-helm --version 1.3.1 --namespace argocd \
    -f clusters/homelab/apps/argocd-image-updater/values.yaml > "$rendered_chart"
  python3 -I scripts/ci/argocd-image-updater-test.py --rendered-chart "$rendered_chart" --unit
'
```

The provider fixture inspects actual provider requests and propagates deliberate
API conflicts. Live Kubernetes is required to verify SSA managed-field semantics.
