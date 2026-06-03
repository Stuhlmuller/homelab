#!/usr/bin/env bash
set -euo pipefail

legacy_state_address="kubernetes_secret_v1.this"
legacy_state_key="IaC/homelab/live/kubernetes-secrets/external-secrets-aws-ssm-auth/terraform.tfstate"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

cat >"${tmp_dir}/backend.tf" <<EOF
terraform {
  backend "s3" {
    bucket       = "rstuhlmuller-aws-s3-use1-datalake"
    key          = "${legacy_state_key}"
    region       = "us-east-1"
    encrypt      = true
    kms_key_id   = "alias/homelab-opentofu"
    use_lockfile = true
  }
}
EOF

cat >"${tmp_dir}/versions.tf" <<'EOF'
terraform {
  required_version = ">= 1.10.0"
}
EOF

(
  cd "${tmp_dir}"
  tofu init -input=false -no-color

  state_list="${tmp_dir}/state-list.txt"
  state_list_err="${tmp_dir}/state-list.err"
  if ! tofu state list >"${state_list}" 2>"${state_list_err}"; then
    if grep -qi "No state file was found" "${state_list_err}"; then
      echo "Legacy External Secrets AWS auth state is absent: ${legacy_state_key}"
      exit 0
    fi

    cat "${state_list_err}" >&2
    exit 1
  fi

  if grep -Fxq "${legacy_state_address}" "${state_list}"; then
    tofu state rm "${legacy_state_address}"
  else
    echo "Legacy External Secrets AWS auth state address is already absent: ${legacy_state_address}"
  fi
)
