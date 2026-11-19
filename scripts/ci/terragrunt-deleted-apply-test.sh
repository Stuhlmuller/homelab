#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fixture="$(mktemp -d)"
trap 'rm -rf "$fixture"' EXIT
fixture="$(cd "$fixture" && pwd -P)"
cd "$fixture"
git init -q
git config user.name Fixture
git config user.email fixture@example.invalid
git config commit.gpgsign false
stack_dir=IaC/homelab/us-west-2/shared
mkdir -p catalog/retired "$stack_dir" policy bin
cat >catalog/retired/terragrunt.hcl <<HCL
terraform {
  source = "."
}
remote_state {
  backend = "local"
  config = { path = "$fixture/retired.tfstate" }
  generate = { path = "backend.tf", if_exists = "overwrite_terragrunt" }
}
HCL
echo 'resource "terraform_data" "retired" { input = "fixture" }' >catalog/retired/main.tf
cat >"$stack_dir/terragrunt.stack.hcl" <<'HCL'
unit "retired" {
  source = "../../../../catalog/retired"
  path   = "retired"
  no_dot_terragrunt_stack = true
}
HCL
git add catalog IaC
git commit -qm 'test: add generated unit'
export APPLY_BASE_SHA="$(git rev-parse HEAD)"
terragrunt stack run --working-dir "$stack_dir" --non-interactive -- apply -auto-approve >setup.log 2>&1 ||
  { cat setup.log >&2; exit 1; }
sed 's/path   = "retired"/path   = "kept"/' "$stack_dir/terragrunt.stack.hcl" >kept.hcl
mv kept.hcl "$stack_dir/terragrunt.stack.hcl"
git add "$stack_dir/terragrunt.stack.hcl"
git commit -qm 'test: remove generated unit'

# Capture the binary at policy evaluation and require byte-for-byte replay.
export fixture REAL_TOFU="$(command -v tofu)" REAL_CONFTEST="$(command -v conftest)"
cat >bin/conftest <<'SH'
#!/usr/bin/env bash
set -euo pipefail
json="${@: -1}"
plan="${json%/tfplan.json}/tfplan.tfplan"
plan="${plan/\/json\/@/\/binary\/@}"
"$REAL_TOFU" show -json "$plan" | jq -S . >"$fixture/binary.json"
jq -S . "$json" | cmp "$fixture/binary.json" -
jq -e '.resource_changes[] | select(.address == "terraform_data.retired" and .change.actions == ["delete"])' "$json" >/dev/null
cp "$plan" "$fixture/checked.tfplan"
exec "$REAL_CONFTEST" "$@"
SH
cat >bin/tofu <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == apply ]]; then
  touch "$fixture/apply-invoked"
  cmp "$fixture/checked.tfplan" "${@: -1}"
fi
exec "$REAL_TOFU" "$@"
SH
chmod +x bin/*
export PATH="$fixture/bin:$PATH"
export RUNNER_TEMP="$fixture"
cat >run-apply <<'SH'
source "$1/terragrunt-filter-base.sh"
repo_root="$PWD"
cleanup_dirs=()
TERRAGRUNT_EFFECTIVE_FILTER_HEAD_REF="$(git rev-parse HEAD)"
verify_current_main_commit() { :; }
source <(sed -n '/^destroy_deleted_terragrunt_units() {$/,/^}$/p' "$1/terragrunt-apply.sh")
destroy_deleted_terragrunt_units
SH

cat >policy/retirement.rego <<'REGO'
package main
deny contains "fixture rejects destroy" if {
  input.resource_changes[_].change.actions == ["delete"]
}
REGO
cp retired.tfstate before.tfstate
# Keep errexit active inside the function even when collecting its exit status.
set +e
bash -euo pipefail run-apply "$source_dir" >reject.log 2>&1
status=$?
set -e
if [[ "$status" == 0 ]] || ! rg -q 'fixture rejects destroy' reject.log || [[ -e apply-invoked ]]; then
  cat reject.log >&2
  exit 1
fi
cmp before.tfstate retired.tfstate

sed 's/\["delete"\]/["create"]/' policy/retirement.rego >policy/allow.rego
rm policy/retirement.rego
bash -euo pipefail run-apply "$source_dir" >allow.log 2>&1 ||
  { cat allow.log >&2; exit 1; }
test -e apply-invoked
jq -e '.resources == []' retired.tfstate >/dev/null
