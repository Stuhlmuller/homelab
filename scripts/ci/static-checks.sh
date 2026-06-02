#!/usr/bin/env bash
set -euo pipefail

echo "::group::Terragrunt HCL"
terragrunt hcl fmt --check
terragrunt hcl validate
echo "::endgroup::"

echo "::group::Kustomize overlays"
while IFS= read -r overlay; do
  echo "rendering ${overlay}"
  kubectl kustomize "$overlay" >/dev/null
done < <(
  find clusters/homelab/argocd clusters/homelab/apps clusters/homelab/platform \
    -name kustomization.yaml \
    -exec dirname {} \; | sort
)
echo "::endgroup::"

echo "::group::Image digest pins"
tag_only_images="$(
  {
    rg -n '^\s*tag:\s*["'\'']?[^"'\''#[:space:]][^#]*$' clusters/homelab || true
    rg -n '^\s*image:\s*[^[:space:]#]+:[^@#[:space:]]+' clusters/homelab || true
  } \
    | rg -v '@sha256:' \
    | rg -v 'clusters/homelab/apps/argocd-image-updater/imageupdater\.yaml:[0-9]+:\s+tag:\s+.*image\.tag$' \
    || true
)"

image_updater_targets=()
if [[ -f clusters/homelab/apps/argocd-image-updater/imageupdater.yaml ]]; then
  while IFS= read -r target; do
    image_updater_targets+=("$target")
  done < <(
    {
      rg -o 'writeBackTarget:\s*"?(helmvalues|kustomization):/[^"[:space:]]+"?' \
        clusters/homelab/apps/argocd-image-updater/imageupdater.yaml || true
    } | sed -E 's#writeBackTarget:[[:space:]]*"?(helmvalues|kustomization):/([^"[:space:]]+)"?#\2#'
  )
fi

unmanaged_tag_only_images=""
if [[ -n "$tag_only_images" ]]; then
  while IFS= read -r image_line; do
    image_file="${image_line%%:*}"
    image_updater_managed=false

    for target in "${image_updater_targets[@]}"; do
      if [[ "$image_file" == "$target" || "$image_file" == "$target"/* ]]; then
        image_updater_managed=true
        break
      fi
    done

    if [[ "$image_updater_managed" == false ]]; then
      unmanaged_tag_only_images+="${image_line}"$'\n'
    fi
  done <<<"$tag_only_images"
fi

if [[ -n "$unmanaged_tag_only_images" ]]; then
  echo "Container images outside Argo CD Image Updater write-back targets must be pinned as tag@sha256:digest:" >&2
  printf '%s\n' "$unmanaged_tag_only_images" >&2
  exit 1
fi
echo "::endgroup::"

echo "::group::Secret scan"
bash scripts/ci/secret-scan.sh
echo "::endgroup::"

echo "::group::Checkov"
if command -v checkov >/dev/null 2>&1; then
  checkov --config-file .checkov.yaml --framework terraform --directory IaC/modules
  checkov --config-file .checkov.yaml --framework kubernetes --directory clusters
  checkov --config-file .checkov.yaml --framework secrets --directory .
elif [[ "${CI:-}" == "true" ]]; then
  echo "checkov is required in CI but was not found in PATH" >&2
  exit 1
else
  echo "::warning::checkov is not available in this local shell; GitHub Actions still enforces Checkov on Linux."
fi
echo "::endgroup::"

echo "::group::Whitespace"
git diff --check
echo "::endgroup::"
