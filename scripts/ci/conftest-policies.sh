#!/usr/bin/env bash
set -euo pipefail

echo "::group::Conftest policies"
yaml_files=()
while IFS= read -r yaml_file; do
  yaml_files+=("$yaml_file")
done < <(
  find .github clusters \
    \( -name '*.yaml' -o -name '*.yml' \) \
    -not -path './.terragrunt-cache/*' \
    -print 2>/dev/null | sort
)

if ((${#yaml_files[@]} > 0)); then
  conftest test --policy policy --output github "${yaml_files[@]}"
fi
echo "::endgroup::"
